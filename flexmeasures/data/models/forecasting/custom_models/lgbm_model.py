from darts.models import LightGBMModel

from flexmeasures.data.models.forecasting.custom_models.base_model import BaseModel


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
        max_forecast_horizon=48,
        probabilistic=True,
        models_params=None,
        auto_regressive=True,
        use_past_covariates=False,
        use_future_covariates=False,
        ensure_positive=False,
    ):

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
        super().__init__(
            max_forecast_horizon=max_forecast_horizon,
            probabilistic=probabilistic,
            auto_regressive=auto_regressive,
            use_past_covariates=use_past_covariates,
            use_future_covariates=use_future_covariates,
            ensure_positive=ensure_positive,
        )

    def _setup(self) -> None:
        for horizon in range(self.max_forecast_horizon):
            model_params = self.models_params.copy()
            model_params["output_chunk_shift"] = (
                horizon  # Shift the output by i hours of each sub-model
            )

            # Lag features are dynamically set based on the forecast horizon
            lag = (
                24
                - (  # temporarily make the adaptation to the sensor resolution; To do: inlude a list of seasonal lags to include, given as pd.timedelta objects
                    horizon % 24
                )
            )  # Adjust to repeat the lag structure every 24 hours
            lags = [-1, -lag, -lag - 1]

            # Special cases for lags
            if (
                horizon == 0
                or horizon % 24 == 0
                or horizon == self.max_forecast_horizon - 1
            ):
                lags = [-1, -24]
            elif horizon % 24 == 23:
                lags = [-1, -2]

            # lags = list(range(-1, -25, -1))  # todo: consider letting the model figure out which lags are important
            model_params["lags"] = lags
            if self.use_past_covariates:
                model_params["lags_past_covariates"] = lags

            # The one future covariate lag that is probably the most important is the one at the `horizon`,
            # but here we pass all future lags up until `max_horizon`, and let the model figure it out.
            # One future covariate that is of considerable importance is the cyclic time encoder, which contains information about the time at the `horizon`,
            # i.e. the time of the event that we forecast, rather than the time at which the forecast is made, which would be at lag `0`.

            model_params["lags_future_covariates"] = lags + [0]

            model = LightGBMModel(**model_params)
            self.models.append(model)
