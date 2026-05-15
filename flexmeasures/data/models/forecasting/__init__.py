from __future__ import annotations

import logging

from copy import deepcopy
from typing import Any

from flexmeasures.data.models.data_sources import DataGenerator
from flexmeasures.data.schemas.forecasting import ForecasterConfigSchema


class SuppressTorchWarning(logging.Filter):
    """Suppress specific Torch warnings from Darts library about model availability."""

    def filter(self, record):
        return "Support for Torch based models not available" not in record.getMessage()


# Apply the filter to Darts.models loggers
logging.getLogger("darts.models").addFilter(SuppressTorchWarning())


class Forecaster(DataGenerator):
    __version__ = None
    __author__ = None
    __data_generator_base__ = "forecaster"

    _config_schema = ForecasterConfigSchema()

    def _compute(
        self, check_output_resolution=True, as_job: bool = False, **kwargs
    ) -> list[dict[str, Any]]:
        """This method triggers the creation of a new forecast.

        The same object can generate multiple forecasts with different start, end, resolution and belief_time values.

        :param check_output_resolution: If True, checks each output for whether the event_resolution
                                        matches that of the sensor it is supposed to be recorded on.
        :param as_job:                  If True, runs as a job.
        """

        results = self._compute_forecast(**kwargs, as_job=as_job)

        if not as_job:
            for result in results:
                # checking that the event_resolution of the output BeliefDataFrame is equal to the one of the output sensor
                assert not check_output_resolution or (
                    result["sensor"].event_resolution == result["data"].event_resolution
                ), f"The resolution of the results ({result['data'].event_resolution}) should match that of the output sensor ({result['sensor'].event_resolution}, ID {result['sensor'].id})."

        return results

    def _compute_forecast(self, as_job: bool = False, **kwargs) -> list[dict[str, Any]]:
        """Overwrite with the actual computation of your forecast.

        :param as_job:  If True, runs as a job.
        :returns:       List of dictionaries, for example:
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

        - end-date:             as the event end
        - max-forecast-horizon: as the maximum belief horizon of the beliefs for a given event
        - forecast-frequency:   as the spacing between unique belief times
        - probabilistic:        as the cumulative_probability of each belief
        - sensor-to-save:       as the sensor on which the beliefs are recorded

        Other:

        - model-save-dir:       used internally for the train and predict pipelines to save and load the model
        - output-path:          for exporting forecasts to file, more of a developer feature
        - as-job:               only indicates whether the computation was offloaded to a worker
        """
        _parameters = deepcopy(parameters)
        # Note: Parameter keys are in kebab-case due to Marshmallow schema data_key settings
        # (see ForecasterParametersSchema in flexmeasures/data/schemas/forecasting/pipeline.py)
        fields_to_remove = [
            "end-date",
            "max-forecast-horizon",
            "forecast-frequency",
            "probabilistic",
            "model-save-dir",
            "output-path",
            "sensor-to-save",
            "as-job",
            "m_viewpoints",  # Computed internally, still uses snake_case
            "sensor",
        ]

        for field in fields_to_remove:
            _parameters.pop(field, None)
        return _parameters


# End of module.
