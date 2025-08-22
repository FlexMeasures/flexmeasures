import os
import sys
import time
import logging
from datetime import datetime, timedelta

from flexmeasures.data.models.time_series import Sensor
from rq.job import Job

from flask import current_app

from flexmeasures.data.models.forecasting.exceptions import CustomException
from flexmeasures.data.models.forecasting.pipelines.predict import PredictPipeline
from flexmeasures.data.models.forecasting.pipelines.train import TrainPipeline
from flexmeasures.utils.flexmeasures_inflection import p


class TrainPredictPipeline:
    def __init__(
        self,
        sensors: dict[str, int],
        regressors: list[str],
        past_regressors: list[str],
        future_regressors: list[str],
        target: Sensor,
        model_save_dir: str,
        output_path: str,
        start_date: datetime,
        end_date: datetime,
        train_period_in_hours: int,
        sensor_to_save: Sensor,
        predict_start: datetime,
        predict_period_in_hours: int,
        max_forecast_horizon: int = 2 * 24,
        forecast_frequency: int = 1,
        probabilistic: bool = False,
        delete_model: bool = False,
    ):
        self.sensors = sensors
        self.regressors = regressors
        self.past_regressors = past_regressors
        self.future_regressors = future_regressors
        self.target = "target"
        self.model_save_dir = model_save_dir
        self.output_path = output_path
        self.start_date = start_date
        self.end_date = end_date
        self.predict_start = predict_start
        self.predict_end = predict_start + timedelta(hours=predict_period_in_hours)
        self.predict_period_in_hours = predict_period_in_hours
        self.train_period_in_hours = train_period_in_hours
        self.max_forecast_horizon = max_forecast_horizon
        self.forecast_frequency = forecast_frequency
        self.probabilistic = probabilistic
        self.sensor_to_save = sensor_to_save
        self.delete_model = delete_model

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
            sensors=self.sensors,
            regressors=self.regressors,
            past_regressors=self.past_regressors,
            future_regressors=self.future_regressors,
            target=self.target,
            model_save_dir=self.model_save_dir,
            n_hours_to_predict=self.train_period_in_hours * multiplier,
            max_forecast_horizon=self.max_forecast_horizon,
            event_starts_after=train_start,
            event_ends_before=train_end,
            probabilistic=self.probabilistic,
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
            sensors=self.sensors,
            regressors=self.regressors,
            past_regressors=self.past_regressors,
            future_regressors=self.future_regressors,
            target=self.target,
            model_path=os.path.join(
                self.model_save_dir,
                f"sensor_{self.sensors[self.target]}-cycle_{counter}-lgbm.pkl",
            ),
            output_path=(
                os.path.join(
                    self.output_path,
                    f"sensor_{self.sensors[self.target]}-cycle_{counter}.csv",
                )
                if self.output_path
                else None
            ),
            n_hours_to_predict=self.predict_period_in_hours * multiplier,
            max_forecast_horizon=self.max_forecast_horizon,
            forecast_frequency=self.forecast_frequency * multiplier,
            probabilistic=self.probabilistic,
            event_starts_after=train_start,  # use beliefs about events before the start of the predict period
            event_ends_before=predict_end,  # ignore any beliefs about events beyond the end of the predict period
            predict_start=predict_start,
            predict_end=predict_end,
            sensor_to_save=self.sensor_to_save,
        )
        logging.info(
            f"Prediction cycle from {predict_start} to {predict_end} started ..."
        )
        predict_start_time = time.time()
        predict_pipeline.run(delete_model=self.delete_model)
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

        return total_runtime

    def run(
        self,
        as_job: bool = False,
        queue: str = "forecasting",
        **job_kwargs,
    ):
        try:
            logging.info(
                f"Starting Train-Predict Pipeline to predict for {self.predict_period_in_hours} hours."
            )

            train_start = self.start_date
            train_end = train_start + timedelta(hours=self.train_period_in_hours)
            predict_start = self.predict_start
            predict_end = predict_start + timedelta(hours=self.predict_period_in_hours)
            counter = 0

            sensor_resolution = Sensor.query.get(
                self.sensors[self.target]
            ).event_resolution
            multiplier = int(
                timedelta(hours=1) / sensor_resolution
            )  # multiplier used to adapt n_hours_to_predict to hours from sensor resolution e,g  15 min sensor resolution will have 7*24*4 = 168 predicitons to predict a week

            cumulative_cycles_runtime = 0  # To track the cumulative runtime of TrainPredictPipeline cycles when not running as a job.
            cycles_job_params = []
            while predict_end <= self.end_date:
                counter += 1

                train_predict_params = {
                    "train_start": train_start,
                    "train_end": train_end,
                    "predict_start": predict_start,
                    "predict_end": predict_end,
                    "counter": counter,
                    "multiplier": multiplier,
                }

                if not as_job:
                    cycle_runtime = self.run_cycle(**train_predict_params)
                    cumulative_cycles_runtime += cycle_runtime
                else:
                    train_predict_params["target_sensor_id"] = self.sensors[self.target]
                    cycles_job_params.append(train_predict_params)

                # Move forward to the next cycle one prediction period later
                cycle_frequency = timedelta(hours=self.predict_period_in_hours)
                train_end += cycle_frequency
                predict_start += cycle_frequency
                predict_end += cycle_frequency
            if counter == 0:
                logging.info(
                    f"Train-Predict Pipeline Not Run: --start-predict-date + --predict-period is {predict_end}, which exceeds --end-date {self.end_date}. "
                    f"Try decreasing the predict-period."
                )
            elif not as_job:
                logging.info(
                    f"Train-Predict Pipeline completed successfully in {cumulative_cycles_runtime:.2f} seconds."
                )

            if as_job:
                jobs = []
                for param in cycles_job_params:
                    job = Job.create(
                        self.run_cycle,
                        kwargs=param,
                        connection=current_app.queues[queue].connection,
                        ttl=int(
                            current_app.config.get(
                                "FLEXMEASURES_JOB_TTL", timedelta(-1)
                            ).total_seconds()
                        ),
                        **job_kwargs,
                    )

                    jobs.append(job)

                    current_app.queues[queue].enqueue_job(job)
                    current_app.job_cache.add(
                        self.sensors[self.target],
                        job_id=job.id,
                        queue=queue,
                        asset_or_sensor_type="sensor",
                    )
                return jobs
        except Exception as e:
            raise CustomException(f"Error running Train-Predict Pipeline: {e}", sys)
