import logging
import os
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

from darts import TimeSeries

from flexmeasures.data.models.forecasting.utils import negative_to_zero


def default_n_jobs() -> int:
    """Number of horizon sub-models to fit or predict at the same time.

    A long forecast horizon on a high-resolution sensor creates hundreds of sub-models, one per horizon.
    Nothing is shared between them, so they are worked on concurrently.
    Each sub-model is expected to run single-threaded, which keeps the total thread count at one per core.
    """
    return os.cpu_count() or 1


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
        n_jobs: int | None = None,
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
        self.n_jobs = max(1, n_jobs if n_jobs is not None else default_n_jobs())
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
        logging.debug("Training base model")

        def fit_one(model):
            model.fit(
                series=series,
                past_covariates=past_covariates,
                future_covariates=future_covariates,
            )

        self._map_over_horizons(fit_one)
        logging.debug("Base model trained successfully")

    def _map_over_horizons(self, work) -> list:
        """Apply ``work`` to every horizon sub-model, concurrently where that helps.

        Results are returned in horizon order, whether or not threads are used.
        The sub-models share no state, so that order is the only thing concurrency could disturb.
        """
        models = self.models[: self.max_forecast_horizon]
        if self.n_jobs == 1 or len(models) < 2:
            return [work(model) for model in models]
        with ThreadPoolExecutor(max_workers=min(self.n_jobs, len(models))) as pool:
            return list(pool.map(work, models))

    def predict(
        self,
        series: TimeSeries,
        past_covariates: TimeSeries,
        future_covariates: TimeSeries,
        num_samples=500,
    ) -> TimeSeries:
        optional_params = {"num_samples": num_samples} if self.probabilistic else {}

        def predict_one(model):
            y_pred = model.predict(
                n=1,
                series=series,
                past_covariates=past_covariates,
                future_covariates=future_covariates,
                **optional_params,
            )
            if self.ensure_positive:
                y_pred = y_pred.map(negative_to_zero)
            return y_pred

        # Predictions come back in horizon order, so they append into one series just as they did when predicted in a loop.
        y_preds_per_horizon = self._map_over_horizons(predict_one)
        if not y_preds_per_horizon:
            raise ValueError(
                f"Cannot forecast without a horizon to forecast for: max_forecast_horizon is {self.max_forecast_horizon}, so no sub-model was set up."
            )
        y_preds = y_preds_per_horizon[0]
        for y_pred in y_preds_per_horizon[1:]:
            y_preds = y_preds.append(other=y_pred)
        return y_preds
