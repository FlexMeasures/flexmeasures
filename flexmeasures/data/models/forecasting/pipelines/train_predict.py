from __future__ import annotations

from typing import Any

import os
import time
import logging
from datetime import datetime, timedelta

from rq.job import Job
from sqlalchemy import inspect as sa_inspect

from flask import current_app

from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.forecasting import Forecaster
from flexmeasures.data.models.forecasting.pipelines.predict import PredictPipeline
from flexmeasures.data.models.forecasting.pipelines.train import TrainPipeline
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.forecasting.pipeline import (
    ForecasterParametersSchema,
    TrainPredictPipelineConfigSchema,
)
from flexmeasures.utils.flexmeasures_inflection import p


def _sensor_id(sensor: Sensor | int | None) -> int | None:
    """Return the sensor ID from a Sensor object or already-serialized ID."""
    if sensor is None:
        return None
    return sensor.id if isinstance(sensor, Sensor) else sensor


def _get_attached_sensor(sensor_id: int | None) -> Sensor | None:
    """Load a sensor in the current session from a queued job payload ID."""
    if sensor_id is None:
        return None
    attached_sensor = db.session.get(Sensor, sensor_id)
    if attached_sensor is None:
        raise ValueError(f"Could not load sensor with id {sensor_id}.")
    return attached_sensor


def _get_attached_data_source(data_source_id: int | None) -> DataSource | None:
    """Load a data source in the current session from a queued job payload ID."""
    if data_source_id is None:
        return None
    attached_source = db.session.get(DataSource, data_source_id)
    if attached_source is None:
        raise ValueError(f"Could not load data source with id {data_source_id}.")
    return attached_source


def _assert_no_orm_objects(value: Any, path: str = "payload") -> None:
    """Reject ORM objects before they can be pickled into an RQ job."""
    inspection = sa_inspect(value, raiseerr=False)
    if inspection is not None and hasattr(inspection, "object"):
        raise ValueError(
            f"Queued forecasting job {path} contains a "
            f"{value.__class__.__name__} ORM object. Pass its ID instead."
        )

    if isinstance(value, dict):
        for key, nested_value in value.items():
            _assert_no_orm_objects(nested_value, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set)):
        for index, nested_value in enumerate(value):
            _assert_no_orm_objects(nested_value, f"{path}[{index}]")


def _make_job_config_payload(config: dict[str, Any]) -> dict[str, Any]:
    """Build the queued worker config payload.

    ORM-backed fields are replaced by IDs, while plain config fields are preserved.
    """
    # Preserve plain config fields, but replace ORM-backed regressors by IDs.
    payload = dict(config)
    future_regressors = payload.pop("future_regressors", [])
    past_regressors = payload.pop("past_regressors", [])
    payload["future_regressor_ids"] = [
        _sensor_id(sensor) for sensor in future_regressors
    ]
    payload["past_regressor_ids"] = [_sensor_id(sensor) for sensor in past_regressors]
    _assert_no_orm_objects(payload)
    return payload


def _load_job_config_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Restore worker config and reload regressors in the worker session."""
    config = dict(payload)
    config["future_regressors"] = [
        _get_attached_sensor(sensor_id)
        for sensor_id in config.pop("future_regressor_ids", [])
    ]
    config["past_regressors"] = [
        _get_attached_sensor(sensor_id)
        for sensor_id in config.pop("past_regressor_ids", [])
    ]
    return config


def _make_job_parameters_payload(parameters: dict[str, Any]) -> dict[str, Any]:
    """Build the queued worker parameter payload.

    ORM-backed fields are replaced by IDs, while plain parameter fields are preserved.
    """
    # Preserve plain parameters, but replace ORM-backed sensors by IDs.
    payload = dict(parameters)
    sensor_id = _sensor_id(payload.pop("sensor"))
    sensor_to_save_id = _sensor_id(payload.pop("sensor_to_save", None))
    if sensor_id is None:
        raise ValueError("Cannot enqueue a forecasting job without a target sensor.")
    payload["sensor_id"] = sensor_id
    payload["sensor_to_save_id"] = sensor_to_save_id or sensor_id
    _assert_no_orm_objects(payload)
    return payload


def _load_job_parameters_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Restore worker parameters and reload sensors in the worker session."""
    parameters = dict(payload)
    parameters["sensor"] = _get_attached_sensor(parameters.pop("sensor_id"))
    parameters["sensor_to_save"] = _get_attached_sensor(
        parameters.pop("sensor_to_save_id")
    )
    return parameters


def run_train_predict_cycle_job(
    config: dict,
    parameters: dict,
    data_source_id: int,
    delete_model: bool,
    **cycle_params,
):
    """Run one train-predict cycle after reconstructing worker-local ORM state."""
    pipeline = TrainPredictPipeline(delete_model=delete_model)
    pipeline._config = _load_job_config_payload(config)
    for key, value in pipeline._config.items():
        setattr(pipeline, key, value)
    pipeline._parameters = _load_job_parameters_payload(parameters)
    pipeline._data_source = _get_attached_data_source(data_source_id)
    return pipeline.run_cycle(**cycle_params)


def run_train_predict_wrap_up_job(cycle_job_ids: list[str], queue: str = "forecasting"):
    """Log the status of all cycle jobs after completion."""
    connection = current_app.queues[queue].connection

    for index, job_id in enumerate(cycle_job_ids):
        status = Job.fetch(job_id, connection=connection).get_status()
        logging.info(f"{queue} job-{index}: {job_id} status: {status}")


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

    def run_wrap_up(self, cycle_job_ids: list[str], queue: str = "forecasting"):
        """Log the status of all cycle jobs after completion."""
        run_train_predict_wrap_up_job(cycle_job_ids, queue)

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
            save_belief_time=self._parameters["save_belief_time"],
            beliefs_before=self._parameters.get("beliefs_before"),
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
            beliefs_before=self._parameters.get("beliefs_before"),
            predict_start=predict_start,
            predict_end=predict_end,
            sensor_to_save=self._parameters["sensor_to_save"],
            data_source=self.data_source,
            missing_threshold=self._config.get("missing_threshold"),
            post_processing_config={
                "lower": self._config.get("lower"),
                "upper": self._config.get("upper"),
                "snap": self._config.get("snap"),
            },
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
        # DataGenerator.compute already loaded kwargs into self._parameters.
        return self.run(as_job=as_job)

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
    ):
        logging.info(
            f"Starting Train-Predict Pipeline to predict for {self._parameters['predict_period_in_hours']} hours."
        )
        connection = current_app.queues[queue].connection
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
        )  # multiplier used to adapt n_steps_to_predict to hours from sensor resolution, e.g. 15 min sensor resolution will have 7*24*4 = 168 predictions to predict a week

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

            job_config = _make_job_config_payload(self._config)
            job_parameters = _make_job_parameters_payload(self._parameters)
            sensor_id = job_parameters["sensor_id"]
            sensor_to_save_id = job_parameters["sensor_to_save_id"]

            # Ensure the data source ID is available in the database when the job runs.
            self._data_source = db.session.merge(self.data_source)
            db.session.flush()
            data_source_id = self._data_source.id
            db.session.commit()

            # job metadata for tracking
            # Serialize start and end to ISO format strings
            # Workaround for https://github.com/Parallels/rq-dashboard/issues/510
            job_metadata = {
                "data_source_info": {"id": data_source_id},
                "start": self._parameters["predict_start"].isoformat(),
                "end": self._parameters["end_date"].isoformat(),
                "sensor_id": sensor_to_save_id,
            }
            if self._job_trigger:
                job_metadata["trigger"] = self._job_trigger
            for cycle_params in cycles_job_params:
                job_kwargs = {
                    "config": job_config,
                    "parameters": job_parameters,
                    "data_source_id": data_source_id,
                    "delete_model": self.delete_model,
                    **cycle_params,
                }
                _assert_no_orm_objects(job_kwargs)

                job = Job.create(
                    run_train_predict_cycle_job,
                    kwargs=job_kwargs,
                    connection=connection,
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
                    sensor_id,
                    job_id=job.id,
                    queue=queue,
                    asset_or_sensor_type="sensor",
                )

            wrap_up_job = Job.create(
                run_train_predict_wrap_up_job,
                kwargs={
                    "cycle_job_ids": cycle_job_ids,
                    "queue": queue,
                },  # cycles jobs IDs to wait for
                connection=connection,
                depends_on=cycle_job_ids,  # wrap-up job depends on all cycle jobs
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
            )
            current_app.queues[queue].enqueue_job(wrap_up_job)

            if len(cycle_job_ids) > 1:
                # Return the wrap-up job ID if multiple cycle jobs are queued
                return {"job_id": wrap_up_job.id, "n_jobs": len(cycle_job_ids)}
            else:
                # Return the single cycle job ID if only one job is queued
                return {
                    "job_id": (
                        cycle_job_ids[0] if len(cycle_job_ids) == 1 else wrap_up_job.id
                    ),
                    "n_jobs": 1,
                }

        return self.return_values
