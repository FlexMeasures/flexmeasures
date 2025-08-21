import sys
import logging
from abc import ABC, abstractmethod

from darts import TimeSeries

from flexmeasures.data.models.forecasting.utils import negative_to_zero
from flexmeasures.data.models.forecasting.exceptions import CustomException


class BaseModel(ABC):
    """
    Base model for multi-horizon forecasting.

    This class serves as a foundation for forecasting models that predict multiple time steps into the future.
    It supports probabilistic forecasting and ensures that no negative values are returned in the predictions.

    Attributes:
        max_forecast_horizon (int): Maximum forecast horizon, indicating the number of steps ahead to predict.
        probabilistic (bool): Whether the model produces probabilistic forecasts.

    Note:
        Predictions from this model (or its subclasses) will never yield negative values, as any negative
        predictions are automatically set to zero.
    """

    max_forecast_horizon: int
    probabilistic: bool

    def __init__(
        self,
        max_forecast_horizon: int,
        probabilistic: bool,
        auto_regressive: bool,
        use_past_covariates: bool,
        use_future_covariates: bool,
        ensure_positive: bool = False,
    ) -> None:
        self.models = []
        self.max_forecast_horizon = max_forecast_horizon
        self.probabilistic = probabilistic
        self.auto_regressive = auto_regressive
        self.use_past_covariates = use_past_covariates
        self.use_future_covariates = use_future_covariates
        self.ensure_positive = ensure_positive
        self._setup()

    @abstractmethod
    def _setup(self) -> None:
        """
        Set up the model. This method should be implemented by subclasses to perform any additional
        initialization or configuration specific to the model.
        """
        pass

    def get_models(self) -> list:
        return self.models

    def fit(
        self,
        series: TimeSeries,
        past_covariates: TimeSeries,
        future_covariates: TimeSeries,
    ) -> None:
        try:
            logging.debug("Training base model")
            for i in range(self.max_forecast_horizon):
                self.models[i].fit(
                    series=series,
                    past_covariates=past_covariates,
                    future_covariates=future_covariates,
                )
            logging.debug("Base model trained successfully")
        except Exception as e:
            raise CustomException(
                f"Error training base model: {e}. Try decreasing the --start-date.", sys
            )

    def predict(
        self,
        series: TimeSeries,
        past_covariates: TimeSeries,
        future_covariates: TimeSeries,
        num_samples=500,
    ) -> TimeSeries:
        y_preds = TimeSeries
        for i in range(self.max_forecast_horizon):
            optional_params = {"num_samples": num_samples} if self.probabilistic else {}

            y_pred = self.models[i].predict(
                n=1,
                series=series,
                past_covariates=past_covariates,
                future_covariates=future_covariates,
                **optional_params,
            )
            if self.ensure_positive:
                y_pred = y_pred.map(negative_to_zero)
            if i == 0:
                y_preds = y_pred
            else:
                y_preds = y_preds.append(other=y_pred)
        return y_preds
