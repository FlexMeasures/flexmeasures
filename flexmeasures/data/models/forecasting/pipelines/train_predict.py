from __future__ import annotations

from typing import Any

import os
import time
import logging
from datetime import datetime, timedelta

from rq.job import Job

from flask import current_app

from flexmeasures.data.models.forecasting import Forecaster
from flexmeasures.data.models.forecasting.pipelines.predict import PredictPipeline
from flexmeasures.data.models.forecasting.pipelines.train import TrainPipeline
from flexmeasures.data.schemas.forecasting.pipeline import (
    ForecasterParametersSchema,
    TrainPredictPipelineConfigSchema,
)
from flexmeasures.utils.flexmeasures_inflection import p


class TrainPredictPipeline(Forecaster):

    __version__ = "1"
    __author__ = "Seita"

    _config_schema = TrainPredictPipelineConfigSchema()
    _parameters_schema = ForecasterParametersSchema()

    def __init__(
        self,
        config: dict | None = None,
        delete_model: bool = False,
        save_config: bool = True,
        save_parameters: bool = False,
    ):
        super().__init__(
            config=config, save_config=save_config, save_parameters=save_parameters
        )
        for k, v in self._config.items():
            setattr(self, k, v)
        self.delete_model = delete_model
        self.return_values = []  # To store forecasts and jobs

    def run_wrap_up(self, cycle_job_ids: list[str]):
        """Log the status of all cycle jobs after completion."""
        for index, job_id in enumerate(cycle_job_ids):
            logging.info(
                f"forecasting job-{index}: {job_id} status: {Job.fetch(job_id).get_status()}"
            )

    def run_cycle(
        self,
        train_start: datetime,
        train_end: datetime,
        predict_start: datetime,
        predict_end: datetime,
        counter: int,
        multiplier: int,
        **kwargs,
    ):
        """
        Runs a single training and prediction cycle.
        """
        logging.info(
            f"Starting Train-Predict cycle from {train_start} to {predict_end}"
        )

        # Train model
        train_pipeline = TrainPipeline(
            future_regressors=self._config["future_regressors"],
            past_regressors=self._config["past_regressors"],
            target_sensor=self._parameters["sensor"],
            model_save_dir=self._parameters["model_save_dir"],
            n_steps_to_predict=(predict_start - train_start)
            // timedelta(hours=1)
            * multiplier,
            max_forecast_horizon=self._parameters["max_forecast_horizon"]
            // self._parameters["sensor"].event_resolution,
            event_starts_after=train_start,
            event_ends_before=train_end,
            probabilistic=self._parameters["probabilistic"],
            ensure_positive=self._config["ensure_positive"],
            missing_threshold=self._config.get("missing_threshold"),
        )

        logging.info(f"Training cycle from {train_start} to {train_end} started ...")
        train_start_time = time.time()
        train_pipeline.run(counter=counter)
        train_runtime = time.time() - train_start_time
        logging.info(
            f"{p.ordinal(counter)} Training cycle completed in {train_runtime:.2f} seconds."
        )
        # Make predictions
        predict_pipeline = PredictPipeline(
            future_regressors=self._config["future_regressors"],
            past_regressors=self._config["past_regressors"],
            target_sensor=self._parameters["sensor"],
            model_path=os.path.join(
                self._parameters["model_save_dir"],
                f"sensor_{self._parameters['sensor'].id}-cycle_{counter}-lgbm.pkl",
            ),
            output_path=(
                os.path.join(
                    self._parameters["output_path"],
                    f"sensor_{self._parameters['sensor'].id}-cycle_{counter}.csv",
                )
                if self._parameters["output_path"]
                else None
            ),
            n_steps_to_predict=self._parameters["predict_period_in_hours"] * multiplier,
            max_forecast_horizon=self._parameters["max_forecast_horizon"]
            // self._parameters["sensor"].event_resolution,
            forecast_frequency=self._parameters["forecast_frequency"]
            // self._parameters["sensor"].event_resolution,
            probabilistic=self._parameters["probabilistic"],
            event_starts_after=train_start,  # use beliefs about events before the start of the predict period
            event_ends_before=predict_end,  # ignore any beliefs about events beyond the end of the predict period
            save_belief_time=self._parameters["save_belief_time"],
            predict_start=predict_start,
            predict_end=predict_end,
            sensor_to_save=self._parameters["sensor_to_save"],
            data_source=self.data_source,
            missing_threshold=self._config.get("missing_threshold"),
        )
        logging.info(
            f"Prediction cycle from {predict_start} to {predict_end} started ..."
        )
        predict_start_time = time.time()
        forecasts = predict_pipeline.run(delete_model=self.delete_model)
        predict_runtime = time.time() - predict_start_time
        logging.info(
            f"{p.ordinal(counter)} Prediction cycle completed in {predict_runtime:.2f} seconds. "
        )

        total_runtime = (
            train_runtime + predict_runtime
        )  # To track the cumulative runtime of PredictPipeline and TrainPipeline for this cycle
        logging.info(
            f"{p.ordinal(counter)} Train-Predict cycle from {train_start} to {predict_end} completed in {total_runtime:.2f} seconds."
        )
        self.return_values.append(
            {"data": forecasts, "sensor": self._parameters["sensor"]}
        )
        return total_runtime

    def _compute_forecast(self, as_job: bool = False, **kwargs) -> list[dict[str, Any]]:
        # Run the train-and-predict pipeline
        return self.run(as_job=as_job, **kwargs)

    def _derive_training_period(self) -> tuple[datetime, datetime]:
        """Derive the effective training period for model fitting.

        The training period ends at ``predict_start`` and starts at the
        most restrictive (latest) of the following:

        - The configured ``start_date`` (if any)
        - ``predict_start - train_period_in_hours`` (if configured)
        - ``predict_start - max_training_period`` (always enforced)

        Additionally, the resulting training window is guaranteed to span
        at least two days.

        :return:    A tuple ``(train_start, train_end)`` defining the training window.
        """
        train_end = self._parameters["predict_start"]

        configured_start: datetime | None = self._config.get("train_start")
        period_hours: int | None = self._config.get("train_period_in_hours")

        candidates: list[datetime] = []

        if configured_start is not None:
            candidates.append(configured_start)

        if period_hours is not None:
            candidates.append(train_end - timedelta(hours=period_hours))

        # Always enforce maximum training period
        candidates.append(train_end - self._config["max_training_period"])

        train_start = max(candidates)

        # Enforce minimum training period of 2 days
        min_training_period = timedelta(days=2)
        if train_end - train_start < min_training_period:
            train_start = train_end - min_training_period

        return train_start, train_end

    def run(
        self,
        as_job: bool = False,
        queue: str = "forecasting",
        **job_kwargs,
    ):
        logging.info(
            f"Starting Train-Predict Pipeline to predict for {self._parameters['predict_period_in_hours']} hours."
        )
        # How much to move forward to the next cycle one prediction period later
        cycle_frequency = max(
            self._config["retrain_frequency"],
            self._parameters["forecast_frequency"],
        )

        predict_start = self._parameters["predict_start"]
        predict_end = predict_start + cycle_frequency

        # Determine training window (start, end)
        train_start, train_end = self._derive_training_period()

        sensor_resolution = self._parameters["sensor"].event_resolution
        multiplier = int(
            timedelta(hours=1) / sensor_resolution
        )  # multiplier used to adapt n_steps_to_predict to hours from sensor resolution, e.g. 15 min sensor resolution will have 7*24*4 = 168 predicitons to predict a week

        # Compute number of training cycles (at least 1)
        n_cycles = max(
            timedelta(hours=self._parameters["predict_period_in_hours"])
            // max(
                self._config["retrain_frequency"],
                self._parameters["forecast_frequency"],
            ),
            1,
        )

        cumulative_cycles_runtime = 0  # To track the cumulative runtime of TrainPredictPipeline cycles when not running as a job.
        cycles_job_params = []
        for counter in range(n_cycles):
            predict_end = min(predict_end, self._parameters["end_date"])

            train_predict_params = {
                "train_start": train_start,
                "train_end": train_end,
                "predict_start": predict_start,
                "predict_end": predict_end,
                "counter": counter + 1,
                "multiplier": multiplier,
            }

            if not as_job:
                cycle_runtime = self.run_cycle(**train_predict_params)
                cumulative_cycles_runtime += cycle_runtime
            else:
                train_predict_params["target_sensor_id"] = self._parameters["sensor"].id
                cycles_job_params.append(train_predict_params)

            train_end += cycle_frequency
            predict_start += cycle_frequency
            predict_end += cycle_frequency
        if not as_job:
            logging.info(
                f"Train-Predict Pipeline completed successfully in {cumulative_cycles_runtime:.2f} seconds."
            )

        if as_job:
            cycle_job_ids = []

            # job metadata for tracking
            job_metadata = {
                "data_source_info": {"id": self.data_source.id},
                "start": self._parameters["predict_start"],
                "end": self._parameters["end_date"],
                "sensor_id": self._parameters["sensor_to_save"].id,
            }
            for cycle_params in cycles_job_params:

                job = Job.create(
                    self.run_cycle,
                    # Some cycle job params override job kwargs
                    kwargs={**job_kwargs, **cycle_params},
                    connection=current_app.queues[queue].connection,
                    ttl=int(
                        current_app.config.get(
                            "FLEXMEASURES_JOB_TTL", timedelta(-1)
                        ).total_seconds()
                    ),
                    result_ttl=int(
                        current_app.config.get(
                            "FLEXMEASURES_PLANNING_TTL", timedelta(-1)
                        ).total_seconds()
                    ),  # NB job.cleanup docs says a negative number of seconds means persisting forever
                    meta=job_metadata,
                    timeout=60 * 60,  # 1 hour
                )

                # Store the job ID for this cycle
                cycle_job_ids.append(job.id)

                current_app.queues[queue].enqueue_job(job)
                current_app.job_cache.add(
                    self._parameters["sensor"].id,
                    job_id=job.id,
                    queue=queue,
                    asset_or_sensor_type="sensor",
                )

            wrap_up_job = Job.create(
                self.run_wrap_up,
                kwargs={"cycle_job_ids": cycle_job_ids},  # cycles jobs IDs to wait for
                connection=current_app.queues[queue].connection,
                depends_on=cycle_job_ids,  # wrap-up job depends on all cycle jobs
                ttl=int(
                    current_app.config.get(
                        "FLEXMEASURES_JOB_TTL", timedelta(-1)
                    ).total_seconds()
                ),
                meta=job_metadata,
            )
            current_app.queues[queue].enqueue_job(wrap_up_job)

            if len(cycle_job_ids) > 1:
                # Return the wrap-up job ID if multiple cycle jobs are queued
                return wrap_up_job.id
            else:
                # Return the single cycle job ID if only one job is queued
                return cycle_job_ids[0] if len(cycle_job_ids) == 1 else wrap_up_job.id

        return self.return_values
