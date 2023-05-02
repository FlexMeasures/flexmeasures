from typing import Optional, Union, Dict

import pandas as pd

from flexmeasures.data.schemas.reporting import ReporterConfigSchema
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.data_sources import DataGeneratorMixin


from datetime import datetime, timedelta

import timely_beliefs as tb


class Reporter(DataGeneratorMixin):
    """Superclass for all FlexMeasures Reporters."""

    __version__ = None
    __author__ = None
    __data_generator_base__ = "Reporter"

    sensor: Sensor = None

    reporter_config: Optional[dict] = None
    reporter_config_raw: Optional[dict] = None
    schema = ReporterConfigSchema
    data: Dict[str, Union[tb.BeliefsDataFrame, pd.DataFrame]] = None
    start: datetime = None
    end: datetime = None
    input_resolution: timedelta = None
    belief_time: datetime = None

    def __init__(
        self, sensor: Sensor, reporter_config_raw: Optional[dict] = None
    ) -> None:
        """
        Initialize a new Reporter.

        Attributes:
        :param sensor: sensor where the output of the reporter will be saved to.
        :param reporter_config_raw: unserialized configuration of the reporter.
        """

        self.sensor = sensor

        if not reporter_config_raw:
            reporter_config_raw = {}

        self.reporter_config_raw = reporter_config_raw

    def fetch_data(self):
        """
        Fetches the time_beliefs from the database
        """

        self.data = {}
        for tb_query in self.tb_query_config:
            _tb_query = tb_query.copy()
            # using start / end instead of event_starts_after/event_ends_before when not defined
            event_starts_after = _tb_query.pop("event_starts_after", self.start)
            event_ends_before = _tb_query.pop("event_ends_before", self.end)
            resolution = _tb_query.pop("resolution", self.input_resolution)
            belief_time = _tb_query.pop("belief_time", self.belief_time)

            sensor: Sensor = _tb_query.pop("sensor", None)
            alias: str = _tb_query.pop("alias", None)

            bdf = sensor.search_beliefs(
                event_starts_after=event_starts_after,
                event_ends_before=event_ends_before,
                resolution=resolution,
                beliefs_before=belief_time,
                **_tb_query,
            )

            # store data source as local variable
            for source in bdf.sources.unique():
                self.data[f"source_{source.id}"] = source

            # store BeliefsDataFrame as local variable
            if alias:
                self.data[alias] = bdf
            else:
                self.data[f"sensor_{sensor.id}"] = bdf

    def update_attribute(self, attribute, default):
        if default is not None:
            setattr(self, attribute, default)

    def compute(
        self,
        *args,
        start: datetime = None,
        end: datetime = None,
        input_resolution: timedelta = None,
        belief_time: datetime = None,
        **kwargs,
    ) -> tb.BeliefsDataFrame:
        """This method triggers the creation of a new report.

        The same object can generate multiple reports with different start, end, input_resolution
        and belief_time values.

        In the future, this function will parse arbitrary input arguments defined in a schema.
        """

        # deserialize configuration
        if self.reporter_config is None:
            self.deserialize_config()

        # if provided, update the class attributes
        self.update_attribute("start", start)
        self.update_attribute("end", end)
        self.update_attribute("input_resolution", input_resolution)
        self.update_attribute("belief_time", belief_time)

        # fetch data
        self.fetch_data()

        # Result
        result = self._compute()

        # checking that the event_resolution of the output BeliefDataFrame is equal to the one of the output sensor
        assert self.sensor.event_resolution == result.event_resolution

        # Assign sensor to BeliefDataFrame
        result.sensor = self.sensor

        return result

    def _compute(self) -> tb.BeliefsDataFrame:
        """
        Overwrite with the actual computation of your report.

        :returns BeliefsDataFrame: report as a BeliefsDataFrame.
        """
        raise NotImplementedError()

    def deserialize_config(self):
        """
        Check all configurations we have, throwing either ValidationErrors or ValueErrors.
        Other code can decide if/how to handle those.
        """
        self.deserialize_reporter_config()
        self.deserialize_timing_config()

    def deserialize_timing_config(self):
        """
        Check if the timing of the report is valid.

        Raises ValueErrors.
        """

        for tb_query in self.tb_query_config:
            start = tb_query.get("event_starts_after", self.start)
            end = tb_query.get("event_ends_before ", self.end)

            if (
                start is not None and end is not None
            ):  # not testing when start or end are missing
                if end < start:
                    raise ValueError(f"Start {start} cannot be after end {end}.")

    def deserialize_reporter_config(self):
        """
        Validate the report config against a Marshmallow Schema.
        Ideas:
        - Override this method
        - Call superclass method to apply validation and common variables deserialization (see PandasReporter)
        - (Partially) extract the relevant reporter_config parameters into class attributes.

        Raises ValidationErrors or ValueErrors.
        """

        self.reporter_config = self.schema.load(
            self.reporter_config_raw
        )  # validate reporter config
        self.tb_query_config = self.reporter_config.get(
            "tb_query_config"
        )  # extracting TimeBelief query configuration parameters
        self.start = self.reporter_config.get("start")
        self.end = self.reporter_config.get("end")
        self.input_resolution = self.reporter_config.get("input_resolution")
        self.belief_time = self.reporter_config.get("belief_time")
