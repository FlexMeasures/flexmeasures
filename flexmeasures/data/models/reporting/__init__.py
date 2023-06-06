from __future__ import annotations
from typing import Optional


from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.data_sources import DataGeneratorMixin

import timely_beliefs as tb


class Reporter(DataGeneratorMixin):
    """Superclass for all FlexMeasures Reporters."""

    __version__ = None
    __author__ = None
    __data_generator_base__ = "Reporter"

    sensor: Sensor = None

    reporter_config: Optional[dict] = None
    report_config: Optional[dict] = None

    reporter_config_schema = None
    report_config_schema = None

    def __init__(self, sensor: Sensor, reporter_config: dict = {}) -> None:
        """
        Initialize a new Reporter.

        Attributes:
        :param sensor: sensor where the output of the reporter will be saved to.
        :param reporter_config: dictionary with the serialized configuration of the reporter.
        """

        self.deserialize_reporter_config(reporter_config)
        self.sensor = sensor

    def update_attribute(self, attribute, default):
        if default is not None:
            setattr(self, attribute, default)

    def compute(self, **kwargs) -> tb.BeliefsDataFrame:
        """This method triggers the creation of a new report.

        The same object can generate multiple reports with different start, end, resolution
        and belief_time values.

        In the future, this function will parse arbitrary input arguments defined in a schema.
        """

        # Result
        result: tb.BeliefsDataFrame = self._compute(**kwargs)

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

    def _compute(self, **kwargs) -> tb.BeliefsDataFrame:
        """
        Overwrite with the actual computation of your report.

        :returns BeliefsDataFrame: report as a BeliefsDataFrame.
        """
        raise NotImplementedError()

    def deserialize_reporter_config(self, reporter_config: dict) -> dict:
        """
        Validate the reporter config against a Marshmallow Schema.
        Ideas:
        - Override this method
        - Call superclass method to apply validation and common variables deserialization (see PandasReporter)
        - (Partially) extract the relevant reporter_config parameters into class attributes.

        Raises ValidationErrors or ValueErrors.
        """

        raise NotImplementedError()

    def deserialize_report_config(self, report_config: dict) -> dict:
        """_summary_

        :param report_config: _description_
        :return: _description_
        """

        raise NotImplementedError()
