from typing import Optional
from datetime import timedelta

from statsmodels.api import OLS

from flexmeasures.data.models.forecasting.model_spec_factory import (
    create_initial_model_specs,
)

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


class Naive(OLS):
    """Naive prediction model for a single input feature that simply throws back the given feature.
    Under the hood, it uses linear regression by ordinary least squares, trained with points (0,0) and (1,1)."""

    def __init__(self, *args, **kwargs):
        super().__init__([0, 1], [0, 1])


def naive_specs_configurator(**kwargs):
    """Create and customize initial specs with OLS. See model_spec_factory for param docs."""
    kwargs["transform_to_normal"] = False
    kwargs["use_regressors"] = False
    kwargs["use_periodicity"] = False
    kwargs["custom_model_params"] = dict(
        training_and_testing_period=timedelta(hours=0), n_lags=1
    )
    model_specs = create_initial_model_specs(**kwargs)
    model_specs.set_model(Naive, library_name="statsmodels")
    model_identifier = "naive model v%d" % version
    return model_specs, model_identifier, fallback_model_search_term
