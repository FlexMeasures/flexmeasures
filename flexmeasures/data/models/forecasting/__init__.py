from __future__ import annotations

from typing import Callable

from timetomodel import ModelSpecs

from flexmeasures.data.models.forecasting.model_specs.naive import (
    naive_specs_configurator as naive_specs,
)
from flexmeasures.data.models.forecasting.model_specs.linear_regression import (
    ols_specs_configurator as linear_ols_specs,
)


model_map = {
    "naive": naive_specs,
    "linear": linear_ols_specs,
    "linear-ols": linear_ols_specs,
}  # use lower case only


def lookup_model_specs_configurator(
    model_search_term: str = "linear-OLS",
) -> Callable[
    ...,  # See model_spec_factory.create_initial_model_specs for an up-to-date type annotation
    # Annotating here would require Python>=3.10 (specifically, ParamSpec from PEP 612)
    tuple[ModelSpecs, str, str],
]:
    """
    This function maps a model-identifying search term to a model configurator function, which can make model meta data.
    Why use a string? It might be stored on RQ jobs. It might also leave more freedom, we can then
    map multiple terms to the same model or vice versa (e.g. when different versions exist).

    Model meta data in this context means a tuple of:
        * timetomodel.ModelSpecs. To fill in those specs, a configurator should accept:
          - old_sensor: Union[Asset, Market, WeatherSensor],
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
    if model_search_term.lower() not in model_map.keys():
        raise Exception("No model found for search term '%s'" % model_search_term)
    return model_map[model_search_term.lower()]
