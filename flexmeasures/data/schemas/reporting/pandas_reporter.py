from marshmallow import Schema, fields, ValidationError, validates_schema
from inspect import signature

from flexmeasures.data.schemas.reporting import ReporterConfigSchema

from timely_beliefs import BeliefsDataFrame


class PandasMethodCall(Schema):

    df_input = fields.Str()
    df_output = fields.Str()

    method = fields.Str(required=True)
    args = fields.List(fields.Raw())
    kwargs = fields.Dict()

    @validates_schema
    def validate_method_call(self, data, **kwargs):

        method = data["method"]
        method_callable = getattr(
            BeliefsDataFrame, method, None
        )  # what if the object which is applied to is not a BeliefsDataFrame...

        if not callable(method_callable):
            raise ValidationError(
                f"method {method} is not a valid BeliefsDataFrame method."
            )

        method_signature = signature(method_callable)

        try:
            args = data.get("args", []).copy()
            _kwargs = data.get("kwargs", {}).copy()

            args.insert(0, BeliefsDataFrame)

            method_signature.bind(*args, **_kwargs)
        except TypeError:
            raise ValidationError(
                f"Bad arguments or keyword arguments for method {method}"
            )


class PandasReporterConfigSchema(ReporterConfigSchema):
    """
    This schema lists fields that can be used to describe sensors in the optimised portfolio

    Example:

    {
        "input_sensors" : [
            {"sensor" : 1, "alias" : "df1"}
        ],
        "transformations" : [
            {
                "df_input" : "df1",
                "df_output" : "df2",
                "method" : "copy"
            },
            {
                "df_input" : "df2",
                "df_output" : "df2",
                "method" : "sum"
            },
            {
                "method" : "sum",
                "kwargs" : {"axis" : 0}
            }
        ],
        "final_df_output" : "df2"
    """

    transformations = fields.List(fields.Nested(PandasMethodCall()), required=True)
    final_df_output = fields.Str(required=True)

    @validates_schema
    def validate_chaining(self, data, **kwargs):
        """
        This validator ensures that we are always given an input and that the
        final_df_output is computed.
        """

        # create dictionary data with objects of the types that is supposed to be generated
        # loading the initial data, the sensors' data
        fake_data = dict(
            (f"sensor_{s['sensor'].id}", BeliefsDataFrame)
            for s in data.get("beliefs_search_configs")
        )
        final_df_output = data.get("final_df_output")

        previous_df = None
        final_df_output_method = None

        for transformation in data.get("transformations"):

            df_input = transformation.get("df_input", previous_df)
            df_output = transformation.get("df_output", df_input)

            if df_output == final_df_output:
                final_df_output_method = transformation.get("method")

            if not previous_df and not df_input:
                raise ValidationError("Cannot find the input DataFrame.")

            previous_df = df_output  # keeping last BeliefsDataFrame calculation

            fake_data[df_output] = BeliefsDataFrame

        if final_df_output not in fake_data:
            raise ValidationError(
                "Cannot find final output DataFrame among the resulting DataFrames."
            )

        if final_df_output_method in ["resample", "groupby"]:
            raise ValidationError(
                "Final output type cannot by of type `Resampler` or `DataFrameGroupBy`"
            )
