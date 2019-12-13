from typing import Tuple, Callable, Union, Optional
from datetime import datetime, timedelta

from timetomodel import ModelSpecs

from bvp.data.models.forecasting.model_specs.naive import (
    naive_specs_configurator as naive_specs,
)
from bvp.data.models.forecasting.model_specs.linear_regression import (
    ols_specs_configurator as linear_ols_specs,
)
from bvp.data.models.forecasting.model_specs.arima import (
    arima_specs_configurator as arima_specs,
)
from bvp.data.models.forecasting.model_specs.ensemble import (
    adaboost_decision_tree_specs_configurator as adaboost_specs,
    bagging_decision_tree_specs_configurator as bagging_specs,
)

from bvp.data.models.assets import Asset
from bvp.data.models.markets import Market
from bvp.data.models.weather import WeatherSensor


model_map = {
    "naive": naive_specs,
    "linear": linear_ols_specs,
    "linear-OLS": linear_ols_specs,
    "ARIMA": arima_specs,
    "arima": arima_specs,
    "AdaBoost Decision Tree": adaboost_specs,
    "AdaBoost": adaboost_specs,
    "adaboost": adaboost_specs,
    "ensemble": adaboost_specs,
    "Bagging Decision Tree": bagging_specs,
    "Bagging": bagging_specs,
    "bagging": bagging_specs,
}


def lookup_model_specs_configurator(
    model_search_term: str = "linear-OLS",
) -> Callable[
    [
        Union[Asset, Market, WeatherSensor],
        datetime,
        datetime,
        timedelta,
        Optional[timedelta],
        Optional[dict],
    ],
    Tuple[ModelSpecs, str, str],
]:
    """
    This function maps a model-identifying search term to a model configurator function, which can make model meta data.
    Why use a string? It might be stored on RQ jobs. It might also leave more freedom, we can then
    map multiple terms to the same model or vice versa (e.g. when different versions exist).

    Model meta data in this context means a tuple of:
        * timetomodel.ModelSpecs. To fill in those specs, a configurator should accept:
          - generic_asset: Union[Asset, Market, WeatherSensor],
          - start: datetime,  # Start of forecast period
          - end: datetime,  # End of forecast period
          - horizon: timedelta,  # Duration between time of forecasting and time which is forecast
          - ex_post_horizon: timedelta = None,
          - custom_model_params: dict = None,  # overwrite forecasting params, useful for testing or experimentation
        * a model_identifier (useful in case the model_search_term was generic, e.g. "latest")
        * a fallback_model_search_term: a string which the forecasting machinery can use to choose
                                        a different model (using this mapping again) in case of failure.

       So to implement a model, write such a function and decide here which search term(s) map(s) to it.
    """
    if model_search_term not in model_map.keys():
        raise Exception("No model found for search term '%s'" % model_search_term)
    return model_map[model_search_term]
