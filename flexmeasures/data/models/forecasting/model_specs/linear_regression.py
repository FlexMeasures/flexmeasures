from typing import Optional

from statsmodels.api import OLS

from flexmeasures.data.models.forecasting.model_spec_factory import (
    create_initial_model_specs,
)

"""
Simple linear regression by ordinary least squares.
"""

# update this version if small things like parametrisation change
version: int = 2
# if a forecasting job using this model fails, fall back on this one
fallback_model_search_term: Optional[str] = "naive"


def ols_specs_configurator(**kwargs):
    """Create and customize initial specs with OLS. See model_spec_factory for param docs."""
    model_specs = create_initial_model_specs(**kwargs)
    model_specs.set_model(OLS)
    model_identifier = "linear-OLS model v%d" % version
    return model_specs, model_identifier, fallback_model_search_term
