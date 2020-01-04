from typing import Callable

from bvp.data.models.forecasting.model_specs.naive import NaiveModelSpecs as naive_specs
from bvp.data.models.forecasting.model_specs.linear_regression import (
    LinearOlsModelSpecs as linear_ols_specs,
)
from bvp.data.models.forecasting.model_specs.ensemble import (
    AdaBoostDecisionTreeModelSpecs,
    BaggingDecisionTreeModelSpecs,
    RandomForestModelSpecs,
)
from bvp.data.models.forecasting.model_specs import ChainedModelSpecs
from bvp.data.models.forecasting.utils import get_case_insensitive_key_value


model_map = {
    "naive": NaiveModelSpecs,
    "linear": LinearOlsModelSpecs,
    "Linear-OLS": LinearOlsModelSpecs,
    "AdaBoost Decision Tree": AdaBoostDecisionTreeModelSpecs,
    "adaboost": AdaBoostDecisionTreeModelSpecs,
    "ensemble": AdaBoostDecisionTreeModelSpecs,
    "Bagging Decision Tree": BaggingDecisionTreeModelSpecs,
    "bagging": BaggingDecisionTreeModelSpecs,
    "Random Forest": RandomForestModelSpecs,
    "forest": RandomForestModelSpecs,
}


def lookup_ChainedModelSpecs(
    model_search_term: str = "Linear-OLS",
) -> Callable[..., ChainedModelSpecs]:
    """
    This function maps a model-identifying search term to a chained model specs class, which can then be instantiated.
    Why use a string? It might be stored on RQ jobs. It might also leave more freedom, we can then
    map multiple terms to the same model or vice versa (e.g. when different versions exist).
    NB: look-ups in the model map are case insensitive.

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
    m = get_case_insensitive_key_value(model_map, model_search_term)
    if m is None:
        raise Exception("No model found for search term '%s'" % model_search_term)
    return m
