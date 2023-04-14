import pandas as pd
from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.schemas.reporting.pandas_reporter import (
    PandasReporterConfigSchema,
)


class PandasReporter(Reporter):
    """This reporter applies a series of pandas methods on"""

    __version__ = "1"
    __author__ = None
    schema = PandasReporterConfigSchema()

    def deserialize_report_config(self):
        # call super class deserialize_report_config
        super().deserialize_report_config()

        # extract PandasReporter specific fields
        self.transformations = self.reporter_config.get("transformations")
        self.final_df_output = self.reporter_config.get("final_df_output")

    def _compute(self) -> pd.Series:
        """"""
        # apply pandas transformations to the dataframes in `self.data``
        self.apply_transformations()

        final_output = self.data[self.final_df_output]
        return final_output

    def get_object_or_literal(self, value, method):
        """This method allows using the dataframes as inputs of the Pandas methods that
        are run in the transformations. Make sure that they have been created before accessed.

        This works by putting the symbol `@` in front of the name of the dataframe that we want to reference.
        For instance, to reference the dataframe test_df, which lives in self.data, we would do `@test_df`.

        This functionality is disabled for methods `eval`and `query` to avoid interfering their internal behaviour
        given that they also use `@` to allow using local variables.

        Examples
        >> self.get_object_or_literal(["@sensor_1", "@sensor_2"], "sum")
        [[                    ...n: 0:00:00,                     ...n: 0:00:00]]
        """

        if method in ["eval", "query"]:
            return value

        if isinstance(value, str) and value.startswith("@"):
            value = value.replace("@", "")
            return self.data[value]

        if isinstance(value, list):
            return [self.get_object_or_literal(v, method) for v in value]

        return value

    def process_pandas_args(self, args, method):
        """This method applies the function get_object_or_literal to all the arguments
        to detect where to replace a string "@<object-name>" with the actual object stored in `self.data["<object-name>"]`.
        """
        for i in range(len(args)):
            args[i] = self.get_object_or_literal(args[i], method)
        return args

    def process_pandas_kwargs(self, kwargs, method):
        """This method applies the function get_object_or_literal to all the keyword arguments
        to detect where to replace a string "@<object-name>" with the actual object stored in `self.data["<object-name>"]`.
        """
        for k, v in kwargs.items():
            kwargs[k] = self.get_object_or_literal(v, method)
        return kwargs

    def apply_transformations(self) -> pd.Series:
        """Convert the series using the given list of transformation specs, which is called in the order given.

        Each transformation specs should include a 'method' key specifying a method name of a Pandas DataFrame.

        Optionally, 'args' and 'kwargs' keys can be specified to pass on arguments or keyword arguments to the given method.

        All data exchange is made through the dictionary `self.data`. The superclass Reporter already fetches and saves BeliefDataFrames
        of the input sensors in the fields `sensor_<sensor_id>`. In case you need to perform complex operations on dataframes, you can
        split the operations in several steps and saving the intermediate results using the parameters `df_input` and `df_output` for the
        input and output dataframes, respectively.

        Example:

        The example below converts from hourly meter readings in kWh to electricity demand in kW.
            transformations = [
                {"mehod": "diff"},
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
            args = self.process_pandas_args(transformation.get("args", []), method)
            kwargs = self.process_pandas_kwargs(
                transformation.get("kwargs", {}), method
            )

            self.data[df_output] = getattr(self.data[df_input], method)(*args, **kwargs)

            previous_df = df_output
