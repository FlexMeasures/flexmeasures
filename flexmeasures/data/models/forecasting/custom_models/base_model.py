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
    It supports probabilistic forecasting.

    Design principles for forecasting pipeline:
    - This design follows the *fixed viewpoint forecasting* paradigm: each forecasting cycle retrains
      the model(s) on an extended training window, then generates predictions.
    - A **cycle** consists of training on a chosen window of historical data (the train period),
      followed by generating forecasts over the **predict period**.
    - `self.models` typically stores one model per forecast horizon, so that each step into the future
      can be predicted independently. This is why a dependency exists between `self.max_forecast_horizon`
      and the number of models.
    - Each model must implement both `fit()` and `predict()`.
    - `self._setup()` is called during initialization to prepare these models (subclasses must implement it).
    - Parameters are validated by `ForecasterParametersSchema`, which is also a good place to learn more
      about configuration and expected inputs.

    Attributes:
        max_forecast_horizon (int): Maximum forecast horizon, indicating the number of steps ahead to predict.
        probabilistic (bool): Whether the model produces probabilistic forecasts.

    Note:
        Predictions from this model (or its subclasses) will never yield negative values if
        `ensure_positive=True`, as any negative predictions are automatically set to zero.
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
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
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
        Set up the forecasting models.

        Subclasses must implement this method to populate `self.models`.
        Typically, one model is created per forecast horizon (up to `self.max_forecast_horizon`).
        These models must provide `fit()` and `predict()` methods compatible with darts TimeSeries.
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
                f"Error training base model: {e}. Try decreasing the start-date.", sys
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
