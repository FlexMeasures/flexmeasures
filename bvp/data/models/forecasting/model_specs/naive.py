from typing import Optional
from datetime import timedelta

import statsmodels.api as sm

from . import ChainedModelSpecs

"""
Naive model, which simply copies the measurement from which the forecasts is made. Useful as a fallback.

Technically, the model has no regressors and just one lag - made using the horizon.
The value to be copied is this one lag.
This is because we assume the forecast is made for the very reason that the data point at this lag exists - why else would one make
a prediction from there with this horizon?
"""

# update this version if small things like parametrisation change
version: int = 1
# if a forecasting job using this model fails, fall back on this one
fallback_model_search_term: Optional[str] = None


class Naive(sm.OLS):
    """Naive prediction model for a single input feature that simply throws back the given feature.
    Under the hood, it uses linear regression by ordinary least squares, trained with points (0,0) and (1,1)."""

    def __init__(self, *args, **kwargs):
        super().__init__([0, 1], [0, 1])


class NaiveModelSpecs(ChainedModelSpecs):
    """Model Specs with a naive model."""

    def __init__(self, *args, **kwargs):
        version = 1  # update this version if small things like parametrisation change
        model = Naive
        library_name = "statsmodels"
        model_identifier = "naive model (v%d)" % version
        kwargs["transform_to_normal"] = False
        kwargs["use_regressors"] = False
        kwargs["use_periodicity"] = False
        custom_model_params = kwargs.get("custom_model_params", {})
        custom_model_params["training_and_testing_period"] = timedelta(hours=0)
        custom_model_params["n_lags"] = 1
        kwargs["custom_model_params"] = custom_model_params
        super().__init__(
            model_identifier=model_identifier,
            fallback_model_search_term=fallback_model_search_term,
            model=model,
            library_name=library_name,
            version=version,
            *args,
            **kwargs
        )
