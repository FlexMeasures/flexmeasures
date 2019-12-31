from typing import Optional

import statsmodels.api as sm

from . import ChainedModelSpecs

"""
Simple linear regression by ordinary least squares.
"""

# if a forecasting job using this model fails, fall back on this one
fallback_model_search_term: Optional[str] = "naive"


class LinearOlsModelSpecs(ChainedModelSpecs):
    """Model Specs with a linear OLS model."""

    def __init__(self, *args, **kwargs):
        version = 2  # update this version if small things like parametrisation change
        model_identifier = "Linear-OLS model (v%d)" % version
        model = sm.OLS
        super().__init__(
            model_identifier=model_identifier,
            fallback_model_search_term=fallback_model_search_term,
            model=model,
            version=version,
            *args,
            **kwargs
        )
