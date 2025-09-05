from __future__ import annotations

from typing import Any
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

    def _compute(self, check_output_resolution=True, **kwargs) -> list[dict[str, Any]]:
        """This method triggers the creation of a new report.

        The same object can generate multiple reports with different start, end, resolution and belief_time values.

        :param check_output_resolution: If True, checks each output for whether the event_resolution
                                        matches that of the sensor it is supposed to be recorded on.
        """

        results = self._compute_report(**kwargs)

        for result in results:
            # checking that the event_resolution of the output BeliefDataFrame is equal to the one of the output sensor
            assert not check_output_resolution or (
                result["sensor"].event_resolution == result["data"].event_resolution
            ), f"The resolution of the results ({result['data'].event_resolution}) should match that of the output sensor ({result['sensor'].event_resolution}, ID {result['sensor'].id})."

            # Update the BeliefDataFrame's sensor to be the intended sensor
            result["data"].sensor = result["sensor"]

            # Update all data sources in the BeliefsDataFrame to the data source representing the configured reporter
            if not result["data"].empty:
                result["data"].index = result["data"].index.set_levels(
                    [self.data_source] * len(result["data"]),
                    level="source",
                    verify_integrity=False,
                )

        return results

    def _compute_report(self, **kwargs) -> list[dict[str, Any]]:
        """Overwrite with the actual computation of your report.

        :returns list of dictionaries, for example:
                 [
                     {
                         "sensor": 501,
                         "data": <a BeliefsDataFrame>,
                     },
                 ]
        """
        raise NotImplementedError()
