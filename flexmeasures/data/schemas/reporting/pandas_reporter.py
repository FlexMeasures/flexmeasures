from marshmallow import Schema, fields, ValidationError, validates_schema, validate
from inspect import signature

from flexmeasures.data.schemas import AwareDateTimeField
from flexmeasures.data.schemas.reporting import (
    ReporterConfigSchema,
    ReporterParametersSchema,
)

from flexmeasures.data.schemas.io import RequiredInput, RequiredOutput
from timely_beliefs import BeliefsDataFrame, BeliefsSeries


from pandas.core.resample import Resampler
from pandas.core.groupby.grouper import Grouper


class PandasMethodCall(Schema):

    df_input = fields.Str()
    df_output = fields.Str()

    method = fields.Str(required=True)
    args = fields.List(fields.Raw())
    kwargs = fields.Dict()

    @validates_schema
    def validate_method_call(self, data, **kwargs):
        """Validates the method name and its arguments against a set of base classes.

        This validation ensures that the provided method exists in one of the
        specified base classes (`BeliefsSeries`, `BeliefsDataFrame`, `Resampler`, `Grouper`)
        and that the provided arguments (`args` and `kwargs`) are valid for the method's
        signature.

        Args:
            data (dict): A dictionary containing the method name (`method`) and optionally
                         the method arguments (`args` as a list and `kwargs` as a dictionary).
            **kwargs: Additional keyword arguments passed by the validation framework.

        Raises:
            ValidationError: If the method is not callable in any of the base classes or
                             if the provided arguments do not match the method signature.
        """

        method = data["method"]
        is_callable = []
        bad_arguments = True

        # Iterate through the base classes to validate the method
        for base_class in [BeliefsSeries, BeliefsDataFrame, Resampler, Grouper]:

            # Check if the method exists in the base class
            method_callable = getattr(base_class, method, None)
            if method_callable is None:
                # Method does not exist in this base class
                is_callable.append(False)
                continue

            # Check if the found method is callable
            is_callable.append(callable(method_callable))

            # Retrieve the method's signature for argument validation
            method_signature = signature(method_callable)

            try:
                # Copy `args` and `kwargs` to avoid modifying the input data
                args = data.get("args", []).copy()
                _kwargs = data.get("kwargs", {}).copy()

                # Insert the base class as the first argument to the method (self/cls context)
                args.insert(0, BeliefsDataFrame)

                # Bind the arguments to the method's signature for validation
                method_signature.bind(*args, **_kwargs)
                bad_arguments = False  # Arguments are valid if binding succeeds
            except TypeError:
                # If binding raises a TypeError, the arguments are invalid
                pass

        # Raise an error if all arguments are invalid across all base classes
        if bad_arguments:
            raise ValidationError(
                f"Bad arguments or keyword arguments for method {method}"
            )

        # Raise an error if the method is not callable in any of the base classes
        if not any(is_callable):
            raise ValidationError(
                f"Method {method} is not a valid BeliefsSeries, BeliefsDataFrame, Resampler or Grouper method."
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

    droplevels = fields.Bool(required=False, load_default=False)

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
    use_latest_version_only = fields.Bool(required=False)

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
