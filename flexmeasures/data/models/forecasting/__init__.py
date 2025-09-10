from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from timetomodel import ModelSpecs

from flexmeasures.data.models.data_sources import DataGenerator
from flexmeasures.data.models.forecasting.custom_models.base_model import (  # noqa: F401
    BaseModel,
)
from flexmeasures.data.models.forecasting.model_specs.naive import (
    naive_specs_configurator as naive_specs,
)
from flexmeasures.data.models.forecasting.model_specs.linear_regression import (
    ols_specs_configurator as linear_ols_specs,
)
from flexmeasures.data.schemas.forecasting import ForecasterConfigSchema


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


class Forecaster(DataGenerator):
    __version__ = None
    __author__ = None
    __data_generator_base__ = "forecaster"

    _config_schema = ForecasterConfigSchema()

    def _compute(self, check_output_resolution=True, **kwargs) -> list[dict[str, Any]]:
        """This method triggers the creation of a new forecast.

        The same object can generate multiple forecasts with different start, end, resolution and belief_time values.

        :param check_output_resolution: If True, checks each output for whether the event_resolution
                                        matches that of the sensor it is supposed to be recorded on.
        """

        results = self._compute_forecast(**kwargs)

        for result in results:
            # checking that the event_resolution of the output BeliefDataFrame is equal to the one of the output sensor
            assert not check_output_resolution or (
                result["sensor"].event_resolution == result["data"].event_resolution
            ), f"The resolution of the results ({result['data'].event_resolution}) should match that of the output sensor ({result['sensor'].event_resolution}, ID {result['sensor'].id})."

        return results

    def _compute_forecast(self, **kwargs) -> list[dict[str, Any]]:
        """Overwrite with the actual computation of your forecast.

        :returns list of dictionaries, for example:
                 [
                     {
                         "sensor": 501,
                         "data": <a BeliefsDataFrame>,
                     },
                 ]
        """
        raise NotImplementedError()

    def _clean_parameters(self, parameters: dict) -> dict:
        """Clean out DataGenerator parameters that should not be stored as DataSource attributes.

        These parameters are already contained in the TimedBelief:

        - max_forecast_horizon: as the maximum belief horizon of the beliefs for a given event
        - forecast_frequency:   as the spacing between unique belief times
        - probabilistic:        as the cumulative_probability of each belief
        - sensor_to_save:       as the sensor on which the beliefs are recorded

        Other:

        - model_save_dir:       used internally for the train and predict pipelines to save and load the model
        - output_path:          for exporting forecasts to file, more of a developer feature
        """
        _parameters = deepcopy(parameters)
        fields_to_remove = [
            "max_forecast_horizon",
            "forecast_frequency",
            "probabilistic",
            "model_save_dir",
            "output_path",
            "sensor_to_save",
        ]

        for field in fields_to_remove:
            _parameters.pop(field, None)
        return _parameters
