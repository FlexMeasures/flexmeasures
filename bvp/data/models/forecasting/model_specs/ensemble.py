from typing import Optional

from sklearn.ensemble import BaggingRegressor, AdaBoostRegressor, RandomForestRegressor
from sklearn.tree import DecisionTreeRegressor
import numpy as np

from . import ChainedModelSpecs

"""
Ensemble models.
"""

# if a forecasting job using this model fails, fall back on this one
fallback_model_search_term: Optional[str] = "linear-OLS"


class AdaBoostDecisionTreeModelSpecs(ChainedModelSpecs):
    """Model Specs with a AdaBoost ensemble model and a decision tree model as a weak learner."""

    def __init__(self, *args, **kwargs):
        version = 1  # update this version if small things like parametrisation change
        model_identifier = "AdaBoost Decision Tree model (v%d)" % version
        model = (
            AdaBoostRegressor,
            dict(
                base_estimator=DecisionTreeRegressor(max_depth=4),
                n_estimators=100,
                random_state=np.random.RandomState(1),
            ),
        )
        super().__init__(
            model_identifier=model_identifier,
            fallback_model_search_term=fallback_model_search_term,
            model=model,
            version=version,
            *args,
            **kwargs
        )


class BaggingDecisionTreeModelSpecs(ChainedModelSpecs):
    """Model Specs with a Bagging ensemble model and a decision tree model as a weak learner."""

    def __init__(self, *args, **kwargs):
        version = 1  # update this version if small things like parametrisation change
        model_identifier = "Bagging Decision Tree model (v%d)" % version
        model = (
            BaggingRegressor,
            dict(
                base_estimator=DecisionTreeRegressor(max_depth=4),
                n_estimators=100,
                random_state=np.random.RandomState(1),
            ),
        )
        super().__init__(
            model_identifier=model_identifier,
            fallback_model_search_term=fallback_model_search_term,
            model=model,
            version=version,
            *args,
            **kwargs
        )


class RandomForestModelSpecs(ChainedModelSpecs):
    """Model Specs with a Random Forest ensemble model."""

    def __init__(self, *args, **kwargs):
        version = 1  # update this version if small things like parametrisation change
        model_identifier = "Random Forest model (v%d)" % version
        model = (
            RandomForestRegressor,
            dict(
                n_estimators=100,
                min_samples_split=2,
                min_samples_leaf=2,
                random_state=np.random.RandomState(1),
                oob_score=True,
            ),
        )
        super().__init__(
            model_identifier=model_identifier,
            fallback_model_search_term=fallback_model_search_term,
            model=model,
            version=version,
            *args,
            **kwargs
        )
