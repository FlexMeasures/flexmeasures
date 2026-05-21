from darts.models import LightGBMModel

from flexmeasures.data.models.forecasting.custom_models.base_model import BaseModel


DEFAULT_SEASONAL_LAGS_STEPS = [24]


class CustomLGBM(BaseModel):
    """
    Multi-horizon forecasting model using LightGBM.

    This class implements a forecasting model that utilizes LightGBM (LGBM) for multi-horizon forecasting.
    It inherits from BaseModel and is designed to forecast multiple horizons into the future based on
    the provided maximum forecast horizon.


    Attributes:
        max_forecast_horizon (int): The maximum number of hours into the future for forecasting.
        probabilistic (bool): Flag indicating whether the model is probabilistic.
        models (List): List to hold multiple LGBM models.
    """

    __version__ = "1"
    __author__ = "Seita"

    def __init__(
        self,
        max_forecast_horizon: int = 48,
        probabilistic: bool = True,
        models_params: dict | None = None,
        auto_regressive: bool = True,
        use_past_covariates: bool = False,
        use_future_covariates: bool = False,
        ensure_positive: bool = False,
        seasonal_lags_steps: list[int] | None = None,
        training_sample_count: int | None = None,
        min_samples_per_horizon: int = 2,
    ) -> None:
        """
        Initialize the LightGBM forecasting model.

        :param max_forecast_horizon: Maximum number of sensor-resolution steps to forecast.
        :param probabilistic: Whether to configure LightGBM for quantile predictions.
        :param models_params: Optional LightGBM parameter overrides.
        :param auto_regressive: Whether the target history should provide autoregressive features.
        :param use_past_covariates: Whether past covariates are used for fitting and prediction.
        :param use_future_covariates: Whether future covariates are used for fitting and prediction.
        :param ensure_positive: Whether negative predictions should be clipped to zero.
        :param seasonal_lags_steps: Candidate seasonal lag steps to keep if enough training samples remain.
        :param training_sample_count: Optional number of target training samples, used to decide which lags are eligible.
        :param min_samples_per_horizon: Minimum training rows required for each horizon model.
        """
        if models_params is None:
            self.models_params = {
                "output_chunk_length": 1,
                "likelihood": "quantile",
                "quantiles": [0.1, 0.5, 0.9] if probabilistic else [0.5],
                "random_state": 42,
                "max_depth": 3,
                "min_child_samples": 50,
                "add_encoders": {
                    "cyclic": {
                        "future": [
                            "hour",
                            "dayofweek",
                        ]
                    }  # Cyclic features handled by Darts library
                },
                "verbose": -1,
            }
        else:
            self.models_params = models_params
        if min_samples_per_horizon < 1:
            raise ValueError("min_samples_per_horizon must be at least 1.")

        if seasonal_lags_steps is None:
            seasonal_lags_steps = DEFAULT_SEASONAL_LAGS_STEPS
        self.seasonal_lags_steps = self._validate_lag_candidates(seasonal_lags_steps)
        self.training_sample_count = training_sample_count
        self.min_samples_per_horizon = min_samples_per_horizon
        super().__init__(
            max_forecast_horizon=max_forecast_horizon,
            probabilistic=probabilistic,
            auto_regressive=auto_regressive,
            use_past_covariates=use_past_covariates,
            use_future_covariates=use_future_covariates,
            ensure_positive=ensure_positive,
        )

    @staticmethod
    def _validate_lag_candidates(
        seasonal_lags_steps: list[int],
    ) -> list[int]:
        """Validate lag candidates and return them without duplicates."""
        if any(lag_steps < 1 for lag_steps in seasonal_lags_steps):
            raise ValueError("seasonal_lags_steps values must be at least 1.")
        return list(dict.fromkeys(seasonal_lags_steps))

    def _filter_eligible_lags_for_horizon(self, horizon: int) -> list[int]:
        """Keep lag candidates that leave enough samples for this horizon."""
        if self.training_sample_count is None:
            return self.seasonal_lags_steps

        eligible_lags_steps = [
            lag_steps
            for lag_steps in self.seasonal_lags_steps
            if self.training_sample_count - lag_steps - horizon
            >= self.min_samples_per_horizon
        ]

        if eligible_lags_steps:
            return eligible_lags_steps
        raise ValueError(
            "None of the seasonal_lags_steps values leave enough training samples "
            f"for forecast horizon {horizon}."
        )

    @staticmethod
    def _lags_for_horizon(
        horizon: int, max_forecast_horizon: int, seasonal_lag_steps: int
    ) -> list[int]:
        """Return Darts lags for one seasonal cycle at the given forecast horizon."""
        lag_steps = seasonal_lag_steps - (horizon % seasonal_lag_steps)
        darts_lags = [-lag_steps, -lag_steps - 1]

        if (
            horizon == 0
            or horizon % seasonal_lag_steps == 0
            or horizon == max_forecast_horizon - 1
        ):
            darts_lags = [-seasonal_lag_steps]
        elif horizon % seasonal_lag_steps == seasonal_lag_steps - 1:
            darts_lags = [-2]

        return darts_lags

    def _setup(self) -> None:
        for horizon in range(self.max_forecast_horizon):
            model_params = self.models_params.copy()
            model_params["output_chunk_shift"] = (
                horizon  # Shift the output by i hours of each sub-model
            )

            # Lag features are dynamically set based on the forecast horizon.
            # todo: include a list of seasonal lags as pd.timedelta objects
            eligible_seasonal_lags_steps = self._filter_eligible_lags_for_horizon(
                horizon
            )
            darts_lags = sorted(
                {
                    -1,
                    *(
                        darts_lag
                        for seasonal_lag_steps in eligible_seasonal_lags_steps
                        for darts_lag in self._lags_for_horizon(
                            horizon, self.max_forecast_horizon, seasonal_lag_steps
                        )
                    ),
                }
            )

            # lags = list(range(-1, -25, -1))  # todo: consider letting the model figure out which lags are important
            model_params["lags"] = darts_lags
            if self.use_past_covariates:
                model_params["lags_past_covariates"] = darts_lags

            # The one future covariate lag that is probably the most important is the one at the `horizon`,
            # but here we pass all future lags up until `max_horizon`, and let the model figure it out.
            # One future covariate that is of considerable importance is the cyclic time encoder, which contains information about the time at the `horizon`,
            # i.e. the time of the event that we forecast, rather than the time at which the forecast is made, which would be at lag `0`.

            model_params["lags_future_covariates"] = darts_lags + [0]

            model = LightGBMModel(**model_params)
            self.models.append(model)
