from __future__ import annotations

from typing import Any
from datetime import datetime, timedelta

from flask import current_app
import timely_beliefs as tb

from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.schemas.reporting.pandas_reporter import (
    PandasReporterConfigSchema,
)
from flexmeasures.utils.time_utils import server_now


class PandasReporter(Reporter):
    """This reporter applies a series of pandas methods on"""

    __version__ = "1"
    __author__ = "Seita"
    schema = PandasReporterConfigSchema()
    transformations: list[dict[str, Any]] = None
    final_df_output: str = None

    def deserialize_config(self):
        # call super class deserialize_config
        super().deserialize_config()

        # extract PandasReporter specific fields
        self.transformations = self.reporter_config.get("transformations")
        self.final_df_output = self.reporter_config.get("final_df_output")

    def _compute(
        self,
        start: datetime,
        end: datetime,
        input_resolution: timedelta | None = None,
        belief_time: datetime | None = None,
    ) -> tb.BeliefsDataFrame:
        """
        This method applies the transformations and outputs the dataframe
        defined in `final_df_output` field of the report_config.
        """

        if belief_time is None:
            belief_time = server_now()

        # apply pandas transformations to the dataframes in `self.data`
        self._apply_transformations()

        final_output = self.data[self.final_df_output]

        if isinstance(final_output, tb.BeliefsDataFrame):

            # filing the missing indexes with default values:
            # belief_time=belief_time, cummulative_probability=0.5, source=data_source
            if "belief_time" not in final_output.index.names:
                final_output["belief_time"] = [belief_time] * len(final_output)
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
            final_output = final_output.to_frame("event_value")
            final_output["belief_time"] = belief_time
            final_output["cumulative_probability"] = 0.5
            final_output["source"] = self.data_source
            final_output = final_output.set_index(
                ["belief_time", "source", "cumulative_probability"], append=True
            )

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
