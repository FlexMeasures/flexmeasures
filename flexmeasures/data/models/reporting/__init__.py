from typing import Optional, Union, Dict

import pandas as pd

from flexmeasures.data.schemas.reporting import ReporterConfigSchema
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.data_sources import DataGenerator

import timely_beliefs as tb


class Reporter(DataGenerator):
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

    def fetch_data(self):
        """
        Fetches the time_beliefs from the database
        """

        self.data = {}
        for tb_query in self.tb_query_config:

            # using start / end instead of event_starts_after/event_ends_before when not defined
            event_starts_after = tb_query.pop("event_starts_after", self.start)
            event_ends_before = tb_query.pop("event_ends_before", self.end)
            resolution = tb_query.pop("resolution", self.input_resolution)

            sensor = tb_query.pop("sensor", None)

            bdf = sensor.search_beliefs(
                event_starts_after=event_starts_after,
                event_ends_before=event_ends_before,
                resolution=resolution,
                **tb_query,
            )

            # adding sources
            for source in bdf.sources.unique():
                self.data[f"source_{source.id}"] = source

            # saving bdf
            self.data[
                f"sensor_{sensor.id}"
            ] = bdf  # TODO: Add alias to reference dataframes easily. e.g: dict(sensor = 1, alias="power"),

    def compute(self, *args, **kwargs) -> tb.BeliefsDataFrame:
        """This method triggers the creation of a new report. This method allows to update the fields
        in reporter_config_raw passing them as keyword arguments or the whole `reporter_config_raw` by
        passing it in the kwarg `reporter_config_raw`.

            Overall, this method follows these steps:
                1) Updating the reporter_config with the kwargs of the method compute.
                2) Triggers config deserialization.
                3) Fetches the data of the sensors described by the field `tb_query_config`.
                4) If the output is BeliefsDataFrame, it simplifies it into a DataFrame

        """
        # if report_config in kwargs
        if "reporter_config_raw" in kwargs:
            self.reporter_config_raw.update(kwargs.get("reporter_config_raw"))
        else:  # check for arguments in kwarg that could be potential fields of reporter config
            for key, value in kwargs.items():

                if (
                    key in self.reporter_config_raw
                ):  # update reporter_config_raw with inputs from the method
                    self.reporter_config_raw[key] = value

                if key in ["start", "end"]:  # convert datetime to string
                    self.reporter_config_raw[key] = value.isoformat().replace("+", " ")
                if key in ["input_resolution"]:  # convert timedelta into string
                    self.reporter_config_raw[key] = pd.Timedelta(value).isoformat()

        # deserialize configuration
        self.deserialize_config()

        # fetch data
        self.fetch_data()

        # Result
        result = self._compute()

        # checking that the event_resolution of the output BeliefDataFrame is equal to the one of the output sensor
        assert self.sensor.event_resolution == result.event_resolution

        # Assign sensor to BeliefDataFrame
        result.sensor = self.sensor

        return result

    def _compute(self) -> Optional[tb.BeliefsDataFrame]:
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
