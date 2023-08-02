from __future__ import annotations

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.data_sources import DataGenerator

from flexmeasures.data.schemas.reporting import (
    ReporterParametersSchema,
    ReporterConfigSchema,
)

import timely_beliefs as tb


class Reporter(DataGenerator):
    """Superclass for all FlexMeasures Reporters."""

    __version__ = None
    __author__ = None
    __data_generator_base__ = "reporter"

    sensor: Sensor = None

    _parameters_schema = ReporterParametersSchema()
    _config_schema = ReporterConfigSchema()

    def _compute(self, **kwargs) -> tb.BeliefsDataFrame:
        """This method triggers the creation of a new report.

        The same object can generate multiple reports with different start, end, resolution
        and belief_time values.
        """

        self.sensor = kwargs["sensor"]

        # Result
        result: tb.BeliefsDataFrame = self._compute_report(**kwargs)

        # checking that the event_resolution of the output BeliefDataFrame is equal to the one of the output sensor
        assert (
            self.sensor.event_resolution == result.event_resolution
        ), f"The resolution of the results ({result.event_resolution}) should match that of the output sensor ({self.sensor.event_resolution}, ID {self.sensor.id})."

        # Assign sensor to BeliefDataFrame
        result.sensor = self.sensor

        if result.empty:
            return result

        # update data source
        result.index = result.index.set_levels(
            [self.data_source] * len(result), level="source", verify_integrity=False
        )

        return result

    def _compute_report(self, **kwargs) -> tb.BeliefsDataFrame:
        """
        Overwrite with the actual computation of your report.

        :returns BeliefsDataFrame: report as a BeliefsDataFrame.
        """
        raise NotImplementedError()
