from __future__ import annotations

from typing import Any
from datetime import datetime, timedelta
from copy import deepcopy, copy

from flask import current_app
from flexmeasures.utils.unit_utils import convert_units
import timely_beliefs as tb
import pandas as pd
from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.schemas.reporting.pandas_reporter import (
    PandasReporterConfigSchema,
    PandasReporterParametersSchema,
)
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.data_sources import keep_latest_version
from flexmeasures.utils.time_utils import server_now


class PandasReporter(Reporter):
    """This reporter applies a series of pandas methods on"""

    __version__ = "1"
    __author__ = "Seita"

    _config_schema = PandasReporterConfigSchema()
    _parameters_schema = PandasReporterParametersSchema()

    input: list[str] = None
    transformations: list[dict[str, Any]] = None
    final_df_output: str = None

    data: dict[str, tb.BeliefsDataFrame | pd.DataFrame] = None

    def _get_input_target_unit(self, name: str) -> str | None:
        for required_input in self._config["required_input"]:
            if name in required_input.get("name"):
                return required_input.get("unit")
        return None

    def _get_output_target_unit(self, name: str) -> str | None:
        for required_output in self._config["required_output"]:
            if name in required_output.get("name"):
                return required_output.get("unit")
        return None

    def fetch_data(
        self,
        start: datetime,
        end: datetime,
        input: dict,
        resolution: timedelta | None = None,
        belief_time: datetime | None = None,
        use_latest_version_only: bool = False,
    ):
        """
        Fetches the time_beliefs from the database
        """

        droplevels = self._config.get("droplevels", False)

        self.data = {}
        for input_search_parameters in input:
            _input_search_parameters = input_search_parameters.copy()

            sensor: Sensor = _input_search_parameters.pop("sensor", None)

            name = _input_search_parameters.pop("name", f"sensor_{sensor.id}")

            # using start / end instead of event_starts_after/event_ends_before when not defined
            event_starts_after = _input_search_parameters.pop(
                "event_starts_after", start
            )
            event_ends_before = _input_search_parameters.pop("event_ends_before", end)
            resolution = _input_search_parameters.pop("resolution", resolution)
            belief_time = _input_search_parameters.pop("belief_time", belief_time)
            source = _input_search_parameters.pop(
                "source", _input_search_parameters.pop("sources", None)
            )

            if use_latest_version_only and source is None:
                source = sensor.search_data_sources(
                    event_ends_after=start,
                    event_starts_before=end,
                    source_types=_input_search_parameters.get("source_types"),
                    exclude_source_types=_input_search_parameters.get(
                        "exclude_source_types"
                    ),
                )
                if len(source) > 0:
                    source = keep_latest_version(source)

            bdf = sensor.search_beliefs(
                event_starts_after=event_starts_after,
                event_ends_before=event_ends_before,
                resolution=resolution,
                beliefs_before=belief_time,
                source=source,
                **_input_search_parameters,
            )

            # store data source as local variable
            for source in bdf.sources.unique():
                self.data[f"source_{source.id}"] = source

            unit = self._get_input_target_unit(name)
            if unit is not None:
                bdf *= convert_units(
                    1,
                    from_unit=sensor.unit,
                    to_unit=unit,
                    event_resolution=sensor.event_resolution,
                )
            if droplevels:
                # dropping belief_time, source and cummulative_probability columns
                bdf = bdf.droplevel([1, 2, 3])
                assert (
                    bdf.index.is_unique
                ), "BeliefDataframe has more than one row per event."

            # store BeliefsDataFrame as local variable
            self.data[name] = bdf

    def _compute_report(self, **kwargs) -> list[dict[str, Any]]:
        """
        This method applies the transformations and outputs the dataframe
        defined in `final_df_output` field of the report_config.
        """

        # report configuration
        start: datetime = kwargs.get("start")
        end: datetime = kwargs.get("end")
        input: dict = kwargs.get("input")

        resolution: timedelta | None = kwargs.get("resolution", None)
        belief_time: datetime | None = kwargs.get("belief_time", None)
        belief_horizon: timedelta | None = kwargs.get("belief_horizon", None)
        output: list[dict[str, Any]] = kwargs.get("output")
        use_latest_version_only: bool = kwargs.get("use_latest_version_only", False)

        # by default, use the minimum resolution among the input sensors
        if resolution is None:
            resolution = min([i["sensor"].event_resolution for i in input])

        # fetch sensor data
        self.fetch_data(
            start, end, input, resolution, belief_time, use_latest_version_only
        )

        if belief_time is None:
            belief_time = server_now()
        # apply pandas transformations to the dataframes in `self.data`
        self._apply_transformations()

        results = []

        for output_description in output:
            result = copy(output_description)

            name = output_description["name"]

            output_data = self.data[name]

            if isinstance(output_data, tb.BeliefsDataFrame):
                # if column is missing, use the first column
                column = output_description.get("column", output_data.columns[0])
                output_data = output_data.rename(columns={column: "event_value"})[
                    ["event_value"]
                ]
                output_data = self._clean_belief_dataframe(
                    output_data, belief_time, belief_horizon
                )

            elif isinstance(output_data, tb.BeliefsSeries):
                output_data = self._clean_belief_series(
                    output_data, belief_time, belief_horizon
                )
            output_unit = self._get_output_target_unit(name)
            if output_unit is not None:
                output_data *= convert_units(
                    1,
                    from_unit=output_unit,
                    to_unit=output_description["sensor"].unit,
                    event_resolution=output_description["sensor"].event_resolution,
                )

            result["data"] = output_data

            results.append(result)

        return results

    def _clean_belief_series(
        self,
        belief_series: tb.BeliefsSeries,
        belief_time: datetime | None = None,
        belief_horizon: timedelta | None = None,
    ) -> tb.BeliefsDataFrame:
        """Create a BeliefDataFrame from a BeliefsSeries creating the necessary indexes."""

        belief_series = belief_series.to_frame("event_value")
        if belief_horizon is not None:
            belief_time = (
                belief_series["event_start"]
                + belief_series.event_resolution
                - belief_horizon
            )
        belief_series["belief_time"] = belief_time
        belief_series["cumulative_probability"] = 0.5
        belief_series["source"] = self.data_source
        belief_series = belief_series.set_index(
            ["belief_time", "source", "cumulative_probability"], append=True
        )

        return belief_series

    def _clean_belief_dataframe(
        self,
        bdf: tb.BeliefsDataFrame,
        belief_time: datetime | None = None,
        belief_horizon: timedelta | None = None,
    ) -> tb.BeliefsDataFrame:
        """Add missing indexes to build a proper BeliefDataFrame."""

        # filing the missing indexes with default values:
        if "belief_time" not in bdf.index.names:
            if belief_horizon is not None:
                # In case that all the index but `event_start` are dropped
                if (
                    isinstance(bdf.index, pd.DatetimeIndex)
                    and bdf.index.name == "event_start"
                ):
                    event_start = bdf.index
                else:
                    event_start = bdf.index.get_event_values("event_start")

                belief_time = event_start + bdf.event_resolution - belief_horizon
            else:
                belief_time = [belief_time] * len(bdf)
            bdf["belief_time"] = belief_time

            bdf = bdf.set_index("belief_time", append=True)

        if "cumulative_probability" not in bdf.index.names:
            bdf["cumulative_probability"] = [0.5] * len(bdf)
            bdf = bdf.set_index("cumulative_probability", append=True)

        if "source" not in bdf.index.names:
            bdf["source"] = [self.data_source] * len(bdf)
            bdf = bdf.set_index("source", append=True)

        return bdf

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

        for _transformation in self._config.get("transformations"):
            transformation = deepcopy(_transformation)

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
