from __future__ import annotations

from typing import Any, Union, Dict
from datetime import datetime, timedelta

from flask import current_app
import timely_beliefs as tb
import pandas as pd
from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.schemas.reporting.pandas_reporter import (
    PandasReporterReporterConfigSchema,
    PandasReporterReportConfigSchema,
)
from flexmeasures.data.models.time_series import TimedBelief, Sensor
from flexmeasures.utils.time_utils import server_now


class PandasReporter(Reporter):
    """This reporter applies a series of pandas methods on"""

    __version__ = "1"
    __author__ = None

    reporter_config_schema = PandasReporterReporterConfigSchema()
    report_config_schema = PandasReporterReportConfigSchema()

    input_variables: list[str] = None
    transformations: list[dict[str, Any]] = None
    final_df_output: str = None

    data: Dict[str, Union[tb.BeliefsDataFrame, pd.DataFrame]] = None

    def deserialize_reporter_config(self, reporter_config):
        # call super class deserialize_config
        self.reporter_config = self.reporter_config_schema.load(reporter_config)

        # extract PandasReporter specific fields
        self.transformations = self.reporter_config.get("transformations")
        self.input_variables = self.reporter_config.get("input_variables")
        self.final_df_output = self.reporter_config.get("final_df_output")

    def deserialize_report_config(
        self, report_config: dict
    ):  # TODO: move to Reporter class
        self.report_config = self.report_config_schema.load(
            report_config
        )  # validate reporter configs

        input_sensors = report_config.get("input_sensors")

        # check that all input_variables are provided
        for variable in self.input_variables:
            assert (
                variable in input_sensors
            ), f"Required sensor with alias `{variable}` not provided."

    def fetch_data(
        self,
        start: datetime,
        end: datetime,
        input_sensors: dict,
        resolution: timedelta | None = None,
        belief_time: datetime | None = None,
    ):
        """
        Fetches the time_beliefs from the database
        """

        self.data = {}
        for alias, tb_query in input_sensors.items():
            _tb_query = tb_query.copy()

            # using start / end instead of event_starts_after/event_ends_before when not defined
            event_starts_after = _tb_query.pop("event_starts_after", start)
            event_ends_before = _tb_query.pop("event_ends_before", end)
            resolution = _tb_query.pop("resolution", resolution)
            belief_time = _tb_query.pop("belief_time", belief_time)

            sensor: Sensor = _tb_query.pop("sensor", None)

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
            self.data[alias] = bdf

    def _compute(self, **kwargs) -> tb.BeliefsDataFrame:
        """
        This method applies the transformations and outputs the dataframe
        defined in `final_df_output` field of the report_config.
        """

        self.report_config = kwargs

        if "report_config" in kwargs:
            self.deserialize_report_config(kwargs.get("report_config"))

        # report configuration
        start: datetime = self.report_config.get("start")
        end: datetime = self.report_config.get("end")
        input_sensors: dict = self.report_config.get("input_sensors")

        resolution: timedelta | None = self.report_config.get("resolution", None)
        belief_time: datetime | None = self.report_config.get("belief_time", None)

        if resolution is None:
            resolution = self.sensor.event_resolution

        # fetch sensor data
        self.fetch_data(start, end, input_sensors, resolution, belief_time)

        # apply pandas transformations to the dataframes in `self.data`
        self._apply_transformations()

        final_output = self.data[self.final_df_output]

        if isinstance(final_output, tb.BeliefsDataFrame):

            # filing the missing indexes with default values:
            # belief_time=server_now(), cummulative_probability=0.5, source=data_source
            if "belief_time" not in final_output.index.names:
                final_output["belief_time"] = [server_now()] * len(final_output)
                final_output = final_output.set_index("belief_time", append=True)

            if "cumulative_probability" not in final_output.index.names:
                final_output["cumulative_probability"] = [0.5] * len(final_output)
                final_output = final_output.set_index(
                    "cumulative_probability", append=True
                )

            if "source" not in final_output.index.names:
                final_output["source"] = [self.data_source] * len(final_output)
                final_output = final_output.set_index("source", append=True)

            final_output = final_output.reorder_levels(
                tb.BeliefsDataFrame().index.names
            )

        elif isinstance(final_output, tb.BeliefsSeries):

            timed_beliefs = [
                TimedBelief(
                    sensor=final_output.sensor,
                    source=self.data_source,
                    belief_time=server_now(),
                    event_start=event_start,
                    event_value=event_value,
                )
                for event_start, event_value in final_output.iteritems()
            ]
            final_output = tb.BeliefsDataFrame(timed_beliefs)

        return final_output

    def get_object_or_literal(self, value: Any, method: str) -> Any:
        """This method allows using the dataframes as inputs of the Pandas methods that
        are run in the transformations. Make sure that they have been created before accessed.

        This works by putting the symbol `@` in front of the name of the dataframe that we want to reference.
        For instance, to reference the dataframe test_df, which lives in self.data, we would do `@test_df`.

        This functionality is disabled for methods `eval`and `query` to avoid interfering their internal behaviour
        given that they also use `@` to allow using local variables.

        Example:
        >>> self.get_object_or_literal(["@df_wind", "@df_solar"], "sum")
        [<BeliefsDataFrame for Wind Turbine sensor>, <BeliefsDataFrame for Solar Panel sensor>]
        """

        if method in ["eval", "query"]:
            if isinstance(value, str) and value.startswith("@"):
                current_app.logger.debug(
                    "Cannot reference objects in self.data using the method eval or query. That is because these methods use the symbol `@` to make reference to local variables."
                )
            return value

        if isinstance(value, str) and value.startswith("@"):
            value = value.replace("@", "")
            return self.data[value]

        if isinstance(value, list):
            return [self.get_object_or_literal(v, method) for v in value]

        return value

    def _process_pandas_args(self, args: list, method: str) -> list:
        """This method applies the function get_object_or_literal to all the arguments
        to detect where to replace a string "@<object-name>" with the actual object stored in `self.data["<object-name>"]`.
        """
        for i in range(len(args)):
            args[i] = self.get_object_or_literal(args[i], method)
        return args

    def _process_pandas_kwargs(self, kwargs: dict, method: str) -> dict:
        """This method applies the function get_object_or_literal to all the keyword arguments
        to detect where to replace a string "@<object-name>" with the actual object stored in `self.data["<object-name>"]`.
        """
        for k, v in kwargs.items():
            kwargs[k] = self.get_object_or_literal(v, method)
        return kwargs

    def _apply_transformations(self):
        """Convert the series using the given list of transformation specs, which is called in the order given.

        Each transformation specs should include a 'method' key specifying a method name of a Pandas DataFrame.

        Optionally, 'args' and 'kwargs' keys can be specified to pass on arguments or keyword arguments to the given method.

        All data exchange is made through the dictionary `self.data`. The superclass Reporter already fetches BeliefsDataFrames of
        the sensors and saves them in the self.data dictionary fields  `sensor_<sensor_id>`. In case you need to perform complex operations on dataframes, you can
        split the operations in several steps and saving the intermediate results using the parameters `df_input` and `df_output` for the
        input and output dataframes, respectively.

        Example:

        The example below converts from hourly meter readings in kWh to electricity demand in kW.
            transformations = [
                {"method": "diff"},
                {"method": "shift", "kwargs": {"periods": -1}},
                {"method": "head", "args": [-1]},
            ],
        """

        previous_df = None

        for transformation in self.transformations:
            df_input = transformation.get(
                "df_input", previous_df
            )  # default is using the previous transformation output
            df_output = transformation.get(
                "df_output", df_input
            )  # default is OUTPUT = INPUT.method()

            method = transformation.get("method")
            args = self._process_pandas_args(transformation.get("args", []), method)
            kwargs = self._process_pandas_kwargs(
                transformation.get("kwargs", {}), method
            )

            self.data[df_output] = getattr(self.data[df_input], method)(*args, **kwargs)

            previous_df = df_output
