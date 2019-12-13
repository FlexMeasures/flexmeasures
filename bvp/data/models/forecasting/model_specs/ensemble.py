from typing import Optional

from sklearn.ensemble import BaggingRegressor, AdaBoostRegressor, RandomForestRegressor
from sklearn.tree import DecisionTreeRegressor
import numpy as np

from bvp.data.models.forecasting.model_spec_factory import create_initial_model_specs

"""
Ensemble models.
"""

# if a forecasting job using this model fails, fall back on this one
fallback_model_search_term: Optional[str] = "linear-OLS"


def adaboost_decision_tree_specs_configurator(**args):
    """Create and customize initial specs with AdaBoost (decision tree as weak learner).
    See model__spec_factory for param docs."""

    # update this version if small things like parametrisation change
    version: int = 1

    model_specs = create_initial_model_specs(**args)
    model_specs.set_model(
        (
            AdaBoostRegressor,
            dict(
                base_estimator=DecisionTreeRegressor(max_depth=4),
                n_estimators=100,
                random_state=np.random.RandomState(1),
            ),
        )
    )
    model_identifier = "AdaBoost Decision Tree model (v%d)" % version
    return model_specs, model_identifier, fallback_model_search_term


def bagging_decision_tree_specs_configurator(**args):
    """Create and customize initial specs with Bagging (decision tree as weak learner).
    See model__spec_factory for param docs."""

    # update this version if small things like parametrisation change
    version: int = 1

    model_specs = create_initial_model_specs(**args)
    model_specs.set_model(
        (
            BaggingRegressor,
            dict(
                base_estimator=DecisionTreeRegressor(max_depth=4),
                n_estimators=100,
                random_state=np.random.RandomState(1),
            ),
        )
    )
    model_identifier = "Bagging Decision Tree model (v%d)" % version
    return model_specs, model_identifier, fallback_model_search_term


def random_forest_specs_configurator(**args):
    """Create and customize initial specs with Random Forest. See model__spec_factory for param docs."""

    # update this version if small things like parametrisation change
    version: int = 1

    model_specs = create_initial_model_specs(**args)
    model_specs.set_model(
        (
            RandomForestRegressor,
            dict(
                n_estimators=100,
                min_samples_split=2,
                min_samples_leaf=2,
                random_state=np.random.RandomState(1),
                oob_score=True,
            ),
        )
    )
    model_identifier = "Random Forest model (v%d)" % version
    return model_specs, model_identifier, fallback_model_search_term
