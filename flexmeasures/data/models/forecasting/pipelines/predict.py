from __future__ import annotations

import os
import pickle
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from darts import TimeSeries
from timely_beliefs.beliefs.utils import select_most_recent_belief
from flexmeasures.data import db
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.utils import save_to_db

from flexmeasures.data.models.forecasting.utils import data_to_bdf
from flexmeasures.data.models.forecasting.exceptions import CustomException
from flexmeasures.data.models.forecasting.logger import logging
from flexmeasures.data.models.forecasting.pipelines.base import BasePipeline


class PredictPipeline(BasePipeline):
    def __init__(
        self,
        sensors: dict[str, int],
        regressors: list[str],
        future_regressors: list[str],
        target: str,
        model_path: str,
        output_path: str,
        n_hours_to_predict: int,
        max_forecast_horizon: int,
        sensor_to_save: Sensor,
        forecast_frequency: int = 1,
        probabilistic: bool = False,
        quantiles: list[float] | None = None,
        event_starts_after: datetime | None = None,
        event_ends_before: datetime | None = None,
        predict_start: datetime | None = None,
        predict_end: datetime | None = None,
    ) -> None:
        """
        Initialize the PredictPipeline.

        :param sensors: Dictionary mapping custom regressor names to sensor IDs.
        :param regressors: List of custom regressor names.
        :param target: Custom target name.
        :param model_path: Path to the model file.
        :param output_path: Path where predictions will be saved.
        :param n_hours_to_predict: Number of hours to predict into the future.
        :param max_forecast_horizon: Maximum forecast horizon in hours.
        :param quantiles: Optional list of quantiles to predict for probabilistic forecasts. If None, predictions are deterministic.
        :param event_starts_after: Only consider events starting after this time.
        :param event_ends_before: Only consider events ending before this time.
        :param predict_start: Only save events starting after this time.
        :param predict_end: Only save events ending before this time.
        :param forecast_frequency: Create a forecast every Nth interval.
        """
        super().__init__(
            sensors=sensors,
            regressors=regressors,
            future_regressors=future_regressors,
            target=target,
            n_hours_to_predict=n_hours_to_predict,
            max_forecast_horizon=max_forecast_horizon,
            event_starts_after=event_starts_after,
            event_ends_before=event_ends_before,
            forecast_frequency=forecast_frequency,
        )
        self.model_path = model_path
        self.output_path = output_path
        self.probabilistic = probabilistic
        self.quantiles = (
            [0.1, 0.5, 0.9] if not quantiles and probabilistic else quantiles
        )
        self.model = None
        self.predictions: pd.DataFrame = None
        self.forecast_horizon = np.arange(1, max_forecast_horizon + 1)
        self.forecast_frequency = forecast_frequency
        self.sensor_to_save = sensor_to_save
        self.predict_start = predict_start
        self.predict_end = predict_end

        self.sensor_resolution = Sensor.query.get(
            self.sensors[self.target]
        ).event_resolution
        hours, remainder = divmod(self.sensor_resolution.total_seconds(), 3600)
        minutes = remainder // 60
        self.readable_resolution = (
            f"{int(hours)} hour"
            if hours == 1
            else f"{int(hours)} hours" if hours > 1 else f"{int(minutes)} mins"
        )
        self.total_forecast_hours = (
            self.max_forecast_horizon * self.sensor_resolution.total_seconds() / 3600
        )

    def load_model(self):
        """
        Load the model and its metadata from the model_path.
        """
        try:
            logging.debug("Loading model and metadata from %s", self.model_path)
            with open(self.model_path, "rb") as file:
                model = pickle.load(file)
            logging.debug(
                "Model and metadata loaded successfully from %s", self.model_path
            )
            return model
        except Exception as e:
            raise CustomException(f"Error loading model and metadata: {e}", sys)

    def _prepare_df_single_horizon_prediction(
        self, y_pred: TimeSeries, belief_horizon, value_at_belief_horizon, time_offset
    ):
        """
        Prepare the DataFrame for a single prediction.
        Make an additional column for quantiles forecast when probabilistic is True
        """
        try:
            logging.debug(
                f"Preparing DataFrame for predictions: {self.readable_resolution} intervals at offset {time_offset + 1}."
            )

            if self.quantiles:
                y_pred_df = y_pred.quantiles_df((self.quantiles)).T
            else:
                y_pred_df = y_pred.pd_dataframe().T

            y_pred_df.columns = [
                f"{i}h" for i in range(1, self.max_forecast_horizon + 1)
            ]
            y_pred_df.reset_index(inplace=True)
            y_pred_df.insert(0, "datetime", belief_horizon)
            y_pred_df.insert(1, self.target, value_at_belief_horizon)

            if self.quantiles:
                y_pred_df.set_index(
                    ["datetime", self.target, "component"], inplace=True
                )
            else:
                y_pred_df.set_index(["datetime", self.target], inplace=True)

            logging.debug(
                f"DataFrame prepared for predictions: {self.readable_resolution} intervals at offset {time_offset + 1}."
            )
            return y_pred_df
        except Exception as e:
            raise CustomException(f"Error preparing prediction DataFrame: {e}", sys)

    def make_single_horizon_prediction(
        self, model, future_covariates, past_covariates, y, time_offset
    ) -> pd.DataFrame:
        """
        Make a single prediction for the given time offset, which can represent minutes or hours
        based on the sensor resolution. The time offset increments the belief horizon and event time
        in the training data.
        """
        try:
            logging.debug(
                f"Predicting for {self.readable_resolution} offset {time_offset + 1}, forecasting up to ({self.total_forecast_hours} hours) ahead."
            )

            current_y = y
            # CHECK THIS DIAGRAM : https://cloud.seita.nl/index.php/s/FYRgJwE3ER8kTLk
            """past covariates and future_covariates data is loaded initially to extend
            from the beginning of the train_period up to the end of the predict_period PLUS max_forecast_horizon.
            Check load_data in base_pipeline."""

            """ For each single-horizon forecast, past_covariates
            start from the beginning of the training dataset and
            end before the last `n_hours_to_predict` time steps that are yet to be predicted,
            while also shifting by `time_offset` after each horizon.
            and discarding the additional period at the end which extends a period of max_forecast_horizon meant for future_covariates
            """
            if past_covariates is not None:
                past_covariates = past_covariates
            """ For each single-horizon forecast, future covariates
             start from the forecasted horizon
             extend the last `n_hours_to_predict` time steps that are yet to be predicted,
             and the additional period at the end for the last forecasted horizon of the predict_period
             While also shifting by `time_offset` after each horizon.
            """
            if future_covariates is not None:
                future_covariates = future_covariates

            y_pred = model.predict(
                current_y,
                past_covariates=past_covariates,
                future_covariates=future_covariates,
            )

            belief_horizon = current_y.end_time()
            value_at_belief_horizon = current_y.last_value()
            y_pred_df = self._prepare_df_single_horizon_prediction(
                y_pred, belief_horizon, value_at_belief_horizon, time_offset
            )
            logging.debug(
                f"Prediction for {self.readable_resolution} offset {time_offset + 1} completed."
            )
            return y_pred_df
        except Exception as e:
            raise CustomException(
                f"Error predicting for {self.readable_resolution} offset {time_offset}: {e}",
                sys,
            )

    def make_multi_horizon_predictions(
        self, model, future_covariates_list, past_covariates_list, y_list
    ) -> pd.DataFrame:
        """
        Make multiple predictions for the given model, X, and y.
        """
        try:
            logging.debug(
                f"Starting to generate predictions for up to {self.max_forecast_horizon} ({self.readable_resolution}) intervals e,g ({self.total_forecast_hours} hours)."
            )

            n_hours_can_predict = self.n_hours_to_predict
            forecast_frequency = self.forecast_frequency
            # We make predictions up to the last hour in the predict_period
            y_pred_dfs = list()
            for i in range(0, n_hours_can_predict, forecast_frequency):
                future_covariates = (
                    future_covariates_list[i] if future_covariates_list else None
                )
                past_covariates = (
                    past_covariates_list[i] if past_covariates_list else None
                )
                y = y_list[i]

                logging.debug(
                    f"Making prediction for {self.readable_resolution} offset {i + 1}/{n_hours_can_predict}"
                )
                y_pred_df = self.make_single_horizon_prediction(
                    model, future_covariates, past_covariates, y, i
                )
                y_pred_dfs.append(y_pred_df)
            df_res = pd.concat(y_pred_dfs)
            logging.debug("Finished generating predictions.")
            return df_res
        except Exception as e:
            raise CustomException(f"Error generating predictions: {e}", sys)

    def save_results_to_CSV(self, df_pred: pd.DataFrame):
        """
        Save the predictions to a CSV file.
        """
        try:
            logging.debug("Saving predictions to a CSV file.")
            os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
            df_pred.to_csv(self.output_path)
            logging.debug("Successfully saved predictions to %s", self.output_path)

        except Exception as e:
            raise CustomException(f"Error saving predictions: {e}", sys)

    def run(self, delete_model: bool = False):
        """
        Execute the prediction pipeline.
        """
        try:
            df = self.load_data_all_beliefs()
            past_covariates_list, future_covariates_list, y_list = (
                self.split_data_all_beliefs(df, is_predict_pipeline=True)
            )

            model = self.load_model()
            df_pred = self.make_multi_horizon_predictions(
                model, future_covariates_list, past_covariates_list, y_list
            )
            if self.output_path is not None:
                self.save_results_to_CSV(df_pred)
            bdf = data_to_bdf(
                data=df_pred,
                horizon=self.max_forecast_horizon,
                probabilistic=self.probabilistic,
                sensors=self.sensors,
                target_sensor=self.target,
                sensor_to_save=self.sensor_to_save,
                regressors=self.regressors,
            )
            print(bdf)

            # todo: maybe these filters only apply to a live setting
            # Mask beliefs outside the prediction window
            bdf = bdf[bdf.index.get_level_values("event_start") >= self.predict_start]
            bdf = bdf[bdf.index.get_level_values("event_start") < self.predict_end]
            # Keep only the most recent belief
            bdf = select_most_recent_belief(bdf)
            print(bdf)

            save_to_db(
                bdf, save_changed_beliefs_only=False
            )  # save all beliefs of forecasted values even if they are the same values as the previous beliefs.
            db.session.commit()
            logging.info(
                f"Saved predictions to DB with source: {bdf.sources[0]}, sensor: {self.sensor_to_save}, sensor_id: {self.sensor_to_save.id}."
            )
            if delete_model:
                os.remove(self.model_path)

            logging.info("Prediction pipeline completed successfully.")
        except Exception as e:
            raise CustomException(f"Error running pipeline: {e}", sys)
