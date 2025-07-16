from __future__ import annotations

from copy import deepcopy

from typing import List, Dict, Any
from flexmeasures.data.models.data_sources import DataGenerator

from flexmeasures.data.schemas.reporting import (
    ReporterParametersSchema,
    ReporterConfigSchema,
)


class Reporter(DataGenerator):
    """Superclass for all FlexMeasures Reporters."""

    __version__ = None
    __author__ = None
    __data_generator_base__ = "reporter"

    _parameters_schema = ReporterParametersSchema()
    _config_schema = ReporterConfigSchema()

    def _compute(self, check_output_resolution=True, **kwargs) -> List[Dict[str, Any]]:
        """This method triggers the creation of a new report.

        The same object can generate multiple reports with different start, end, resolution
        and belief_time values.

            check_output_resolution (default: True):  set to False to skip the validation of the output event_resolution.
        """

        results: List[Dict[str, Any]] = self._compute_report(**kwargs)

        for result in results:
            # checking that the event_resolution of the output BeliefDataFrame is equal to the one of the output sensor
            assert not check_output_resolution or (
                result["sensor"].event_resolution == result["data"].event_resolution
            ), f"The resolution of the results ({result['data'].event_resolution}) should match that of the output sensor ({result['sensor'].event_resolution}, ID {result['sensor'].id})."

            # Assign sensor to BeliefDataFrame
            result["data"].sensor = result["sensor"]

            if not result["data"].empty:
                # update data source
                result["data"].index = result["data"].index.set_levels(
                    [self.data_source] * len(result["data"]),
                    level="source",
                    verify_integrity=False,
                )

        return results

    def _compute_report(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Overwrite with the actual computation of your report.

        :returns BeliefsDataFrame: report as a BeliefsDataFrame.
        """
        raise NotImplementedError()

    def _clean_parameters(self, parameters: dict) -> dict:
        _parameters = deepcopy(parameters)
        fields_to_remove = ["start", "end", "resolution", "belief_time"]

        for field in fields_to_remove:
            _parameters.pop(field, None)

        fields_to_remove_input = [
            "event_starts_after",
            "event_ends_before",
            "belief_time",
            "resolution",
        ]

        for _input in _parameters["input"]:
            for field in fields_to_remove_input:
                _input.pop(field, None)

        return _parameters
