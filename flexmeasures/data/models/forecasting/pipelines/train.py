from __future__ import annotations

import os
import pickle
import sys
import warnings
from datetime import datetime

from darts import TimeSeries

from flexmeasures.data.models.forecasting.custom_models.lgbm_model import CustomLGBM
from flexmeasures.data.models.forecasting.exceptions import CustomException
from flexmeasures.data.models.forecasting.logger import logging
from flexmeasures.data.models.forecasting.pipelines.base import BasePipeline

warnings.filterwarnings("ignore")


class TrainPipeline(BasePipeline):
    def __init__(
        self,
        sensors: dict[str, int],
        regressors: list[str],
        target: str,
        model_save_dir: str,
        n_hours_to_predict: int,
        max_forecast_horizon: int,
        event_starts_after: datetime | None = None,
        event_ends_before: datetime | None = None,
        probabilistic: bool = False,
    ) -> None:
        """
        Initialize the TrainPipeline.

        :param sensors: Dictionary mapping custom regressor names to sensor IDs.
        :param regressors: List of custom regressor names.
        :param target: Custom target name.
        :param model_save_dir: Directory where the trained model will be saved.
        :param n_hours_to_predict: Number of hours to predict into the future.
        :param max_forecast_horizon: Maximum forecast horizon in hours.
        :param event_starts_after: Only consider events starting after this time.
        :param event_ends_before: Only consider events ending before this time.
        """
        self.model_save_dir = model_save_dir
        self.probabilistic = probabilistic
        self.auto_regressive = (
            True
            if "autoregressive" in regressors or "auto_regressive" in regressors
            else False
        )
        super().__init__(
            sensors,
            regressors,
            target,
            n_hours_to_predict,
            max_forecast_horizon,
            event_starts_after,
            event_ends_before,
        )

    def train_model(self, model, X_train: TimeSeries, y_train: TimeSeries):
        """
        Trains the specified model using the provided training data.
        """
        try:
            X_train = (
                X_train if X_train != [] else None
            )  # X_train empty in case of autorregressive forecasting.
            logging.debug(f"Training model {model.__class__.__name__}")
            model.fit(series=y_train, past_covariates=X_train)
            logging.debug("Model trained successfully")
            return model
        except Exception as e:
            raise CustomException(f"Error training model: {e}", sys)

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
            raise CustomException(f"Error saving model and metadata: {e}", sys)

    def run(self, counter: int):
        """
        Runs the training pipeline.

        This function loads the data, splits it into training and testing sets,
        trains multiple models on the training set, and saves the trained models.
        """
        try:
            df = self.load_data()
            X_train, y_train = self.split_data(df)
            models = {
                f"sensor_{self.sensors[self.target]}-cycle_{counter}-lgbm.pkl": CustomLGBM(
                    max_forecast_horizon=self.max_forecast_horizon,
                    probabilistic=self.probabilistic,
                    auto_regressive=self.auto_regressive,
                )
            }

            for model_name, model in models.items():
                trained_model = self.train_model(model, X_train, y_train)
                self.save_model(trained_model, model_name)

        except Exception as e:
            raise CustomException(f"Error running training pipeline: {e}", sys)
