from marshmallow import Schema, fields, ValidationError, validates_schema, validate
from inspect import signature

from flexmeasures.data.schemas import AwareDateTimeField
from flexmeasures.data.schemas.reporting import (
    ReporterConfigSchema,
    ReporterParametersSchema,
)

from flexmeasures.data.schemas.io import RequiredInput, RequiredOutput
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
            "required_input" : [
                {"name" : "df1", "unit" : "MWh"}
            ],
            "required_output" : [
                {"name" : "df2", "unit" : "kWh"}
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
        }
    """

    required_input = fields.List(
        fields.Nested(RequiredInput()), validate=validate.Length(min=1)
    )
    required_output = fields.List(
        fields.Nested(RequiredOutput()), validate=validate.Length(min=1)
    )
    transformations = fields.List(fields.Nested(PandasMethodCall()), required=True)

    droplevels = fields.Bool(required=False, default=False)

    @validates_schema
    def validate_chaining(self, data, **kwargs):
        """
        This validator ensures that we are always given an input and that the
        final_df_output is computed.
        """

        # fake_data mocks the PandasReporter class attribute data. It contains empty BeliefsDataFrame
        # to simulate the process of applying the transformations.
        fake_data = dict(
            (_input["name"], BeliefsDataFrame) for _input in data.get("required_input")
        )
        output_names = [_output["name"] for _output in data.get("required_output")]

        previous_df = None
        output_method = dict()

        for transformation in data.get("transformations"):

            df_input = transformation.get("df_input", previous_df)
            df_output = transformation.get("df_output", df_input)

            if df_output in output_names:
                output_method[df_output] = transformation.get("method")

            if df_input not in fake_data:
                raise ValidationError("Cannot find the input DataFrame.")

            previous_df = df_output  # keeping last BeliefsDataFrame calculation

            fake_data[df_output] = BeliefsDataFrame

        for _output in output_names:
            if _output not in fake_data:
                raise ValidationError(
                    "Cannot find final output `{_output}` DataFrame among the resulting DataFrames."
                )

            if (_output in output_method) and (
                output_method[_output] in ["resample", "groupby"]
            ):
                raise ValidationError(
                    f"Final output (`{_output}`) type cannot by of type `Resampler` or `DataFrameGroupBy`"
                )


class PandasReporterParametersSchema(ReporterParametersSchema):
    # make start and end optional, conditional on providing the time parameters
    # for the single sensors in `input_variables`
    start = AwareDateTimeField(required=False)
    end = AwareDateTimeField(required=False)
    use_latest_version_only = fields.Bool(required=False, default=False)

    @validates_schema
    def validate_time_parameters(self, data, **kwargs):
        """This method validates that all input sensors have start
        and end parameters available.
        """

        # it's enough to provide a common start and end
        if ("start" in data) and ("end" in data):
            return

        for input_description in data.get("input", []):
            input_sensor = input_description["sensor"]
            if ("event_starts_after" not in input_description) and (
                "start" not in data
            ):
                raise ValidationError(
                    f"Start parameter not provided for sensor {input_sensor}"
                )

            if ("event_ends_before" not in input_description) and ("end" not in data):
                raise ValidationError(
                    f"End parameter not provided for sensor {input_sensor}"
                )
