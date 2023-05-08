from __future__ import annotations
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

    def fetch_data(
        self,
        start: datetime,
        end: datetime,
        input_resolution: timedelta = None,
        belief_time: datetime = None,
    ):
        """
        Fetches the time_beliefs from the database
        """

        self.data = {}
        for tb_query in self.beliefs_search_config_schema:
            _tb_query = tb_query.copy()
            # using start / end instead of event_starts_after/event_ends_before when not defined
            event_starts_after = _tb_query.pop("event_starts_after", start)
            event_ends_before = _tb_query.pop("event_ends_before", end)
            resolution = _tb_query.pop("resolution", input_resolution)
            belief_time = _tb_query.pop("belief_time", belief_time)

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
        start: datetime,
        end: datetime,
        input_resolution: timedelta | None = None,
        belief_time: datetime | None = None,
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

        # fetch data
        self.fetch_data(start, end, input_resolution, belief_time)

        # Result
        result = self._compute(start, end, input_resolution, belief_time)

        # checking that the event_resolution of the output BeliefDataFrame is equal to the one of the output sensor
        assert self.sensor.event_resolution == result.event_resolution

        # Assign sensor to BeliefDataFrame
        result.sensor = self.sensor

        return result

    def _compute(
        self,
        start: datetime,
        end: datetime,
        input_resolution: timedelta = None,
        belief_time: datetime = None,
    ) -> tb.BeliefsDataFrame:
        """
        Overwrite with the actual computation of your report.

        :returns BeliefsDataFrame: report as a BeliefsDataFrame.
        """
        raise NotImplementedError()

    def deserialize_config(self):
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
        self.beliefs_search_config_schema = self.reporter_config.get(
            "beliefs_search_config_schema"
        )  # extracting TimeBelief query configuration parameters
