from __future__ import annotations

import os
import pickle
import sys
import logging
from datetime import datetime

import numpy as np
import pandas as pd
from darts import TimeSeries
from isodate import duration_isoformat
from timely_beliefs import BeliefsDataFrame

from flexmeasures import Sensor, Source
from flexmeasures.data import db
from flexmeasures.data.models.forecasting.utils import data_to_bdf
from flexmeasures.data.models.forecasting.exceptions import CustomException
from flexmeasures.data.models.forecasting.pipelines.base import BasePipeline
from flexmeasures.data.utils import save_to_db


class PredictPipeline(BasePipeline):
    def __init__(
        self,
        future_regressors: list[Sensor],
        past_regressors: list[Sensor],
        target_sensor: Sensor,
        model_path: str,
        output_path: str,
        n_steps_to_predict: int,
        max_forecast_horizon: int,
        sensor_to_save: Sensor,
        forecast_frequency: int = 1,
        probabilistic: bool = False,
        quantiles: list[float] | None = None,
        event_starts_after: datetime | None = None,
        event_ends_before: datetime | None = None,
        predict_start: datetime | None = None,
        predict_end: datetime | None = None,
        data_source: Source = None,
        missing_threshold: float = 1.0,
    ) -> None:
        """
        Initialize the PredictPipeline.

        :param sensors: Dictionary mapping custom regressor names to sensor IDs.
        :param past_regressors: List of sensors serving as past regressors.
        :param future_regressors: List of sensors serving as future regressors.
        :param target: Custom target name.
        :param model_path: Path to the model file.
        :param output_path: Path where predictions will be saved.
        :param n_steps_to_predict: Number of steps of 1 resolution to predict into the future.
        :param max_forecast_horizon: Maximum forecast horizon in steps of 1 resolution.
        :param quantiles: Optional list of quantiles to predict for probabilistic forecasts. If None, predictions are deterministic.
        :param event_starts_after: Only consider events starting after this time.
        :param event_ends_before: Only consider events ending before this time.
        :param predict_start: Only save events starting after this time.
        :param predict_end: Only save events ending before this time.
        :param forecast_frequency: Create a forecast every Nth interval.
        :param data_source: Data source to attribute the forecasts to.
        :param probabilistic: Whether to use a probabilistic model.
        :param sensor_to_save: Sensor to which the predictions will be attributed.
        :param missing_threshold: Max fraction of missing data allowed before failure. Missing data under the threshold will be filled with our interpolation methods.
        """
        super().__init__(
            future_regressors=future_regressors,
            past_regressors=past_regressors,
            target_sensor=target_sensor,
            n_steps_to_predict=n_steps_to_predict,
            max_forecast_horizon=max_forecast_horizon,
            event_starts_after=event_starts_after,
            event_ends_before=event_ends_before,
            forecast_frequency=forecast_frequency,
            predict_start=predict_start,
            predict_end=predict_end,
            missing_threshold=missing_threshold,
        )
        self.model_path = model_path
        self.output_path = output_path
        self.probabilistic = probabilistic
        self.quantiles = tuple(quantiles) if quantiles else None
        self.forecast_horizon = np.arange(1, max_forecast_horizon + 1)
        self.forecast_frequency = forecast_frequency
        self.sensor_to_save = sensor_to_save
        self.predict_start = predict_start
        self.predict_end = predict_end

        self.sensor_resolution = self.target_sensor.event_resolution
        self.readable_resolution = duration_isoformat(self.sensor_resolution)
        self.total_forecast_hours = (
            self.max_forecast_horizon * self.sensor_resolution.total_seconds() / 3600
        )
        self.data_source = data_source

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
            raise CustomException(f"Error loading model and metadata: {e}", sys) from e

    def _prepare_df_single_horizon_prediction(
        self,
        y_pred: TimeSeries,
        belief_horizon,
        value_at_belief_horizon,
        viewpoint: int,
        belief_timestamp,
    ):
        """
        Prepare the DataFrame for a single prediction.
        Make an additional column for quantiles forecast when probabilistic is True
        """
        try:
            logging.debug(f"Preparing DataFrame for viewpoint {viewpoint}.")

            if self.probabilistic:
                q_kwargs = dict(quantiles=self.quantiles) if self.quantiles else dict()
                y_pred_df = y_pred.quantiles_df(**q_kwargs).T
            else:
                try:
                    y_pred_df = y_pred.pd_dataframe().T
                except AttributeError:
                    y_pred_df = y_pred.to_dataframe().T

            y_pred_df.columns = [
                f"{h}h" for h in range(1, self.max_forecast_horizon + 1)
            ]
            y_pred_df.reset_index(inplace=True)
            # Insert forecasts event_start timestamps
            y_pred_df.insert(0, "event_start", belief_horizon)

            # Insert forecasts belief_time timestamps
            y_pred_df.insert(1, "belief_time", belief_timestamp)

            # Insert the target sensor name and value at belief time forecasts are made
            y_pred_df.insert(2, self.target, value_at_belief_horizon)
            if self.quantiles:
                y_pred_df.set_index(
                    ["event_start", "belief_time", self.target, "component"],
                    inplace=True,
                )
            else:
                y_pred_df.set_index(
                    ["event_start", "belief_time", self.target], inplace=True
                )

            logging.debug(f"DataFrame prepared for viewpoint {viewpoint}.")
            return y_pred_df
        except Exception as e:
            raise CustomException(
                f"Error preparing prediction DataFrame: {e}", sys
            ) from e

    def make_single_fixed_viewpoint_prediction(
        self,
        model,
        future_covariates: TimeSeries,
        past_covariates: TimeSeries,
        current_y: TimeSeries,
        viewpoint: int,
        belief_timestamp: pd.Timestamp,
    ) -> pd.DataFrame:
        """
        Make a single prediction for the given viewpoint (enumeration of the number of viewpoints),
        using inputs already sliced for this belief time.
        Notes
        -----
        The covariate/target windowing and belief semantics are documented in:
        - `BasePipeline` class docstring (“Covariate semantics”)
        - `BasePipeline.split_data_all_beliefs` → `_generate_splits`
        """
        try:
            logging.debug(
                f"Predicting for viewpoint {viewpoint}, forecasting up to {self.total_forecast_hours} hours ahead."
            )
            # Inputs (y, past_covariates, future_covariates) are pre-sliced for this
            # belief time by BasePipeline._generate_splits. See BasePipeline docs and
            # CHECK THIS DIAGRAM : https://cloud.seita.nl/index.php/s/FYRgJwE3ER8kTLk aka 20250210_123637.png

            # Get time series of forecasts at a single viewpoint
            y_pred = model.predict(
                current_y,
                past_covariates=past_covariates,
                future_covariates=future_covariates,
            )

            belief_horizon = current_y.end_time()
            value_at_belief_horizon = current_y.last_value()
            y_pred_df = self._prepare_df_single_horizon_prediction(
                y_pred=y_pred,
                belief_horizon=belief_horizon,
                value_at_belief_horizon=value_at_belief_horizon,
                viewpoint=viewpoint,
                belief_timestamp=belief_timestamp,
            )
            logging.debug(f"Prediction for viewpoint {viewpoint} completed.")
            return y_pred_df
        except Exception as e:
            raise CustomException(
                f"Error predicting for viewpoint {viewpoint}: {e}",
                sys,
            ) from e

    def make_multi_fixed_viewpoint_predictions(
        self,
        model,
        future_covariates_list: list[TimeSeries],
        past_covariates_list: list[TimeSeries],
        y_list: list[TimeSeries],
        belief_timestamps_list: list[pd.Timestamp],
    ) -> pd.DataFrame:
        """
        Make predictions for multiple fixed viewpoints, for the given model, X, and y.
        """
        try:
            logging.debug(
                f"Starting to generate predictions for up to {self.max_forecast_horizon} ({self.readable_resolution}) intervals (i.e. {self.total_forecast_hours} hours)."
            )

            # We make predictions up to the last hour in the predict_period
            y_pred_dfs = list()
            for v, belief_timestamp in enumerate(belief_timestamps_list):
                future_covariates = (
                    future_covariates_list[v] if future_covariates_list else None
                )
                past_covariates = (
                    past_covariates_list[v] if past_covariates_list else None
                )
                y = y_list[v]
                logging.debug(
                    f"Making prediction for {belief_timestamp} (viewpoint {v + 1}/{self.number_of_viewpoints})"
                )
                y_pred_df = self.make_single_fixed_viewpoint_prediction(
                    model=model,
                    future_covariates=future_covariates,
                    past_covariates=past_covariates,
                    current_y=y,
                    viewpoint=v + 1,  # humanized iterator starting from 1
                    belief_timestamp=belief_timestamp,
                )
                y_pred_dfs.append(y_pred_df)
            df_res = pd.concat(y_pred_dfs)
            logging.debug("Finished generating predictions.")
            return df_res
        except Exception as e:
            raise CustomException(f"Error generating predictions: {e}", sys) from e

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
            raise CustomException(f"Error saving predictions: {e}", sys) from e

    def run(self, delete_model: bool = False) -> BeliefsDataFrame:
        """
        Execute the prediction pipeline.
        """
        try:
            df = self.load_data_all_beliefs()
            (
                past_covariates_list,
                future_covariates_list,
                y_list,
                belief_timestamps_list,
            ) = self.split_data_all_beliefs(df, is_predict_pipeline=True)
            logging.debug("Done splitting data")

            model = self.load_model()
            logging.debug("Model loaded")
            df_pred = self.make_multi_fixed_viewpoint_predictions(
                model,
                future_covariates_list=future_covariates_list,
                past_covariates_list=past_covariates_list,
                y_list=y_list,
                belief_timestamps_list=belief_timestamps_list,
            )
            logging.debug("Predictions ready to be saved")

            # todo: it looks like data_to_bdf should become a class method
            bdf = data_to_bdf(
                data=df_pred,
                horizon=self.max_forecast_horizon,
                probabilistic=self.probabilistic,
                target_sensor=self.target_sensor,
                sensor_to_save=self.sensor_to_save,
                data_source=self.data_source,
            )
            if self.output_path is not None:
                self.save_results_to_CSV(bdf)

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

            return bdf
        except Exception as e:
            raise CustomException(f"Error running pipeline: {e}", sys) from e
