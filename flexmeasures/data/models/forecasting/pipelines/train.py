from __future__ import annotations

import os
import pickle
import sys
import warnings
import logging
from datetime import datetime

from darts import TimeSeries

from flexmeasures import Sensor
from flexmeasures.data.models.forecasting.custom_models.lgbm_model import CustomLGBM
from flexmeasures.data.models.forecasting.exceptions import CustomException
from flexmeasures.data.models.forecasting.pipelines.base import BasePipeline

warnings.filterwarnings("ignore")


class TrainPipeline(BasePipeline):
    def __init__(
        self,
        sensors: dict[str, int],
        past_regressors: list[str],
        future_regressors: list[str],
        future: list[Sensor],
        past: list[Sensor],
        target_sensor: Sensor,
        model_save_dir: str,
        n_steps_to_predict: int,
        max_forecast_horizon: int,
        forecast_frequency: int = 1,
        event_starts_after: datetime | None = None,
        event_ends_before: datetime | None = None,
        probabilistic: bool = False,
    ) -> None:
        """
        Initialize the TrainPipeline.

        :param sensors: Dictionary mapping custom regressor names to sensor IDs.
        :param past_regressors: List of past regressor names.
        :param future_regressors: List of future regressor names.
        :param target: Custom target name.
        :param model_save_dir: Directory where the trained model will be saved.
        :param n_steps_to_predict: Number of steps of 1 resolution to predict into the future.
        :param max_forecast_horizon: Maximum forecast horizon in steps of 1 resolution.
        :param event_starts_after: Only consider events starting after this time.
        :param event_ends_before: Only consider events ending before this time.
        """
        self.model_save_dir = model_save_dir
        self.probabilistic = probabilistic
        self.auto_regressive = (
            True if not past_regressors and not future_regressors else False
        )
        super().__init__(
            sensors=sensors,
            past_regressors=past_regressors,
            future_regressors=future_regressors,
            future=future,
            past=past,
            target_sensor=target_sensor,
            n_steps_to_predict=n_steps_to_predict,
            max_forecast_horizon=max_forecast_horizon,
            event_starts_after=event_starts_after,
            event_ends_before=event_ends_before,
            forecast_frequency=forecast_frequency,
        )

    def train_model(
        self,
        model,
        future_covariates: TimeSeries,
        past_covariates: TimeSeries,
        y_train: TimeSeries,
    ):
        """
        Trains the specified model using the provided training data.
        """
        try:
            logging.debug(f"Training model {model.__class__.__name__}")

            model.fit(
                series=y_train,
                past_covariates=past_covariates,
                future_covariates=future_covariates,
            )
            logging.debug("Model trained successfully")
            return model
        except Exception as e:
            raise CustomException(f"Error training model: {e}", sys) from e

    def save_model(self, model, model_name: str):
        """
        Save the trained model to the model_save_path.
        """
        try:
            model_save_path = os.path.join(self.model_save_dir, model_name)
            # Ensure the directory exists
            os.makedirs(self.model_save_dir, exist_ok=True)
            with open(model_save_path, "wb") as file:
                pickle.dump(model, file)
            logging.debug(f"Model and metadata saved successfully to {model_save_path}")
        except Exception as e:
            raise CustomException(f"Error saving model and metadata: {e}", sys) from e

    def run(self, counter: int):
        """
        Runs the training pipeline.

        This function loads the data, splits it into training and testing sets,
        trains multiple models on the training set, and saves the trained models.
        """
        try:
            df = self.load_data_all_beliefs()
            past_covariates_list, future_covariates_list, y_train_list, _ = (
                self.split_data_all_beliefs(df)
            )
            past_covariates = past_covariates_list[0] if past_covariates_list else None
            future_covariates = (
                future_covariates_list[0] if future_covariates_list else None
            )
            y_train = y_train_list[0]

            models = {
                f"sensor_{self.target_sensor.id}-cycle_{counter}-lgbm.pkl": CustomLGBM(
                    max_forecast_horizon=self.max_forecast_horizon,
                    probabilistic=self.probabilistic,
                    auto_regressive=self.auto_regressive,
                    use_past_covariates=past_covariates_list is not None,
                    use_future_covariates=future_covariates_list is not None,
                )
            }

            for model_name, model in models.items():
                trained_model = self.train_model(
                    model=model,
                    future_covariates=future_covariates,
                    past_covariates=past_covariates,
                    y_train=y_train,
                )
                self.save_model(trained_model, model_name)

        except Exception as e:
            raise CustomException(f"Error running training pipeline: {e}", sys) from e
