from typing import Callable

from bvp.data.models.forecasting.model_specs.naive import NaiveModelSpecs as naive_specs
from bvp.data.models.forecasting.model_specs.linear_regression import (
    LinearOlsModelSpecs as linear_ols_specs,
)
from bvp.data.models.forecasting.model_specs.ensemble import (
    AdaBoostDecisionTreeModelSpecs as adaboost_specs,
    BaggingDecisionTreeModelSpecs as bagging_specs,
    RandomForestModelSpecs as forest_specs,
)
from bvp.data.models.forecasting.model_specs import ChainedModelSpecs


model_map = {
    "naive": naive_specs,
    "Naive": naive_specs,
    "linear": linear_ols_specs,
    "linear-OLS": linear_ols_specs,
    "Linear-OLS": linear_ols_specs,
    "AdaBoost Decision Tree": adaboost_specs,
    "AdaBoost": adaboost_specs,
    "adaboost": adaboost_specs,
    "ensemble": adaboost_specs,
    "Bagging Decision Tree": bagging_specs,
    "Bagging": bagging_specs,
    "bagging": bagging_specs,
    "Random Forest": forest_specs,
    "random forest": forest_specs,
    "forest": forest_specs,
}


def lookup_ChainedModelSpecs(
    model_search_term: str = "Linear-OLS",
) -> Callable[..., ChainedModelSpecs]:
    """
    This function maps a model-identifying search term to a chained model specs class, which can then be instantiated.
    Why use a string? It might be stored on RQ jobs. It might also leave more freedom, we can then
    map multiple terms to the same model or vice versa (e.g. when different versions exist).

    To instantiate the class use:
    >>> ModelSpecs = lookup_ChainedModelSpecs()
    >>> model_specs = ModelSpecs(generic_asset, forecast_start, forecast_end, forecast_horizon)
    For help on how to instantiate the class, see model_spec_factory.create_init_params().

    The instantiated class then has useful attributes relating to how the models are chained, such as:
    >>> model_specs.model_identifier
    >>> model_specs.fallback_model_search_term
    The model identifier is useful in case the model_search_term was generic, e.g. "latest".
    The fallback model search term is a string which the forecasting machinery can use to choose a different model
    (using this mapping again) in case of failure.

    The instantiated class also has the information you expect to find in an timetomodel.ModelSpecs instance, such as:
    >>> model_specs.start_of_training
    >>> model_specs.model_type
    """
    if model_search_term not in model_map.keys():
        raise Exception("No model found for search term '%s'" % model_search_term)
    return model_map[model_search_term]
