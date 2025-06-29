import os
import sys
import time
from datetime import datetime, timedelta, timezone

from flexmeasures.data.models.time_series import Sensor
from rq.job import Job

from flexmeasures_smartbuildings.models.const import Status
from flexmeasures_smartbuildings.models.jobs import Priority, create_job
from flexmeasures_smartbuildings.models.smartbuilding import SmartBuildingSimulation

from ..exception import CustomException
from ..logger import logging
from .predict_pipeline import PredictPipeline
from .train_pipeline import TrainPipeline


def update_forecasting_status(
    simulation_id: int,
    created_at: datetime = None,
    error: bool = False,
    target_sensor_id: int = None,
):
    """
    Update the status of all scenarios to `FORECASTING_FINISHED` if forecasting jobs run successfully,
    or to `ERROR_DURING_FORECASTING` if an error occurs.
    """
    simulation = SmartBuildingSimulation.fetch(simulation_id)
    scenarios = simulation.scenarios  # get all scenarios for the simulation

    if error:
        simulation.log(
            f"Forecasting pipeline run has failed for sensor {target_sensor_id:} in {simulation.name}.",
            level="ERROR",
        )
        for scenario in scenarios:
            scenario.change_status(Status.ERROR_DURING_FORECASTING)
    else:
        for scenario in scenarios:

            scenario.change_status(Status.FORECASTING_FINISHED)

            pipeline_duration = (
                datetime.now(timezone.utc) - created_at
            ).total_seconds()
        simulation.log(
            f"Forecasting pipeline run has been completed for {simulation.name} in: {pipeline_duration:.2f} seconds.",
        )


def create_train_predict_pipeline_jobs(
    simulation_id: int,
    sensors: list[Sensor],
    start: datetime,
    end: datetime,
    train_period: int,
    predict_period: int,
    max_forecast_horizon: int,
    simulation_job: Job,
    probabilistic: bool = False,
    forecast_frequency: int = 1,
):
    """Run the Train-Predict Pipeline."""
    simulation = SmartBuildingSimulation.fetch(simulation_id)

    cycle_jobs = []
    for sensor in sensors:
        simulation.log(
            f"Running Forecasting Pipeline for sensor `{sensor.name}` with id: {sensor.id}."
        )

        train_predict_pipeline = TrainPredictPipeline(
            sensors={f"{sensor.name}": sensor.id},
            regressors=["auto_regressive"],
            target=sensor.name,
            model_save_dir="flexmeasures/data/models/forecasting/residential/artifacts/models",
            output_path=None,
            start_date=start,
            end_date=end,
            train_period_in_hours=train_period * 24,
            predict_start=start + timedelta(hours=train_period * 24),
            predict_period_in_hours=predict_period * 24,
            max_forecast_horizon=max_forecast_horizon,
            probabilistic=probabilistic,
            sensor_to_save=sensor,
            delete_model=True,
            forecast_frequency=forecast_frequency,
        )

        cycles_job_params = train_predict_pipeline.run(as_job=True)

        for cycle_job_params in cycles_job_params:
            cycle_job_params["simulation_id"] = simulation_id

            job = create_job(
                simulation,
                func=train_predict_pipeline.run_cycle,
                enqueue=True,
                depends_on=simulation_job,
                kwargs=cycle_job_params,
                priority=Priority.HIGH,
            )
            cycle_jobs.append(job)
    return cycle_jobs


class TrainPredictPipeline:
    def __init__(
        self,
        sensors: dict[str, int],
        regressors: list[str],
        target: str,
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
        self.target = target
        self.model_save_dir = model_save_dir
        self.output_path = output_path
        self.start_date = start_date
        self.end_date = end_date
        self.predict_start = predict_start
        self.predict_end = self.predict_start + timedelta(hours=predict_period_in_hours)
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
        simulation_id: int = None,
    ):
        """
        Runs a single training and prediction cycle.
        """
        train_predict_cycle_runtime = 0  # To track the cumulative runtime of PredictPipeline and TrainPipeline for this cycle

        logging.info(
            f"Starting Train-Predict cycle from {train_start} to {predict_end}"
        )

        if simulation_id:
            for scenario in SmartBuildingSimulation.fetch(simulation_id).scenarios:
                # If any forecasting cycle fails, we avoid switching to FORECASTING_RUNNING to preserve the ERROR_DURING_FORECASTING status.
                # Otherwise, when other cycle jobs start, they may override the error status, hiding the failure.
                if scenario.status != Status.ERROR_DURING_FORECASTING:
                    scenario.change_status(Status.FORECASTING_RUNNING)

        # Train model
        train_pipeline = TrainPipeline(
            sensors=self.sensors,
            regressors=self.regressors,
            target=self.target,
            model_save_dir=self.model_save_dir,
            n_hours_to_predict=self.train_period_in_hours * multiplier,
            max_forecast_horizon=self.max_forecast_horizon * multiplier,
            event_starts_after=train_start,
            event_ends_before=train_end,
            probabilistic=self.probabilistic,
        )

        logging.info(f"Training cycle from {train_start} to {train_end} started ...")
        train_start_time = time.time()
        try:
            train_pipeline.run(counter=counter)
        except Exception:
            if simulation_id:
                update_forecasting_status(
                    simulation_id=simulation_id,
                    error=True,
                    target_sensor_id=self.sensors[self.target],
                )
        train_runtime = time.time() - train_start_time
        logging.info(
            f"{counter} Training cycle completed in {train_runtime:.2f} seconds."
        )

        # Make predictions
        predict_pipeline = PredictPipeline(
            sensors=self.sensors,
            regressors=self.regressors,
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
            max_forecast_horizon=self.max_forecast_horizon * multiplier,
            forecast_frequency=self.forecast_frequency * multiplier,
            probabilistic=self.probabilistic,
            event_starts_after=train_start,
            event_ends_before=predict_end,
            sensor_to_save=self.sensor_to_save,
        )
        logging.info(
            f"Prediction cycle from {predict_start} to {predict_end} started ..."
        )
        predict_start_time = time.time()
        predict_pipeline.run(delete_model=self.delete_model)
        predict_runtime = time.time() - predict_start_time
        logging.info(
            f"{counter} Prediction cycle completed in {predict_runtime:.2f} seconds. "
        )

        train_predict_cycle_runtime = train_runtime + predict_runtime

        logging.info(
            f"{counter} Train-Predict cycle from {train_start} to {predict_end} completed in {train_predict_cycle_runtime:.2f} seconds."
        )

        return train_predict_cycle_runtime

    def run(
        self,
        as_job: bool = False,
    ):
        try:
            logging.info("Starting Train-Predict Pipeline")

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

                cycle_start_time = time.time()
                if not as_job:
                    self.run_cycle(
                        train_start=train_start,
                        train_end=train_end,
                        predict_start=predict_start,
                        predict_end=predict_end,
                        counter=counter,
                        multiplier=multiplier,
                    )
                    cumulative_cycles_runtime += time.time() - cycle_start_time
                else:
                    cycles_job_params.append(
                        {
                            "train_start": train_start,
                            "train_end": train_end,
                            "predict_start": predict_start,
                            "predict_end": predict_end,
                            "counter": counter,
                            "multiplier": multiplier,
                        }
                    )

                # Move forward to the next cycle one prediction period later
                cycle_frequency = timedelta(hours=self.predict_period_in_hours)
                train_end += cycle_frequency
                predict_start += cycle_frequency
                predict_end += cycle_frequency
            if counter == 0:
                logging.info("Train-Predict Pipeline Not Run.")
            else:
                if not as_job:
                    logging.info(
                        f"Train-Predict Pipeline completed successfully in {cumulative_cycles_runtime:.2f} seconds."
                    )
            if as_job:
                return cycles_job_params
        except Exception as e:
            raise CustomException(f"Error running Train-Predict Pipeline: {e}", sys)
