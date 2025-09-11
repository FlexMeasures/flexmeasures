from marshmallow import Schema, fields, ValidationError, validates_schema, validate
from inspect import signature
from flask.app import current_app as app
from flexmeasures.data.schemas import AwareDateTimeField
from flexmeasures.data.schemas.reporting import (
    ReporterConfigSchema,
    ReporterParametersSchema,
)

from flexmeasures.data.schemas.io import RequiredInput, RequiredOutput
from timely_beliefs import BeliefsDataFrame, BeliefsSeries


from pandas.core.resample import Resampler
from pandas.core.groupby.grouper import Grouper


# Methods whose Python signature we choose NOT to bind against.
# We’ll do our own strict payload checks instead.
DEFAULT_SKIP_SIGNATURE_METHODS = {"get_attribute", "sensor"}


# Helper: ensure args/kwargs are "primitive-only" (no callables/objects)
def _is_primitive(x) -> bool:
    return isinstance(x, (str, int, float, bool, tuple, list, dict, type(None)))


def _validate_primitive_payload(args, kwargs):
    if not isinstance(args, list) or not isinstance(kwargs, dict):
        raise ValidationError("args must be a list and kwargs must be a dict.")
    if not all(_is_primitive(a) for a in args):
        raise ValidationError("Only primitive values are allowed in args.")
    for k, v in kwargs.items():
        if not isinstance(k, str) or not _is_primitive(v):
            raise ValidationError(
                "Only string keys and primitive values allowed in kwargs."
            )


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
        skip_sig = set(DEFAULT_SKIP_SIGNATURE_METHODS)

        user_defined_methods = app.config.get(
            "FLEXMEASURES_REPORTER_VALIDATION_SKIP_METHODS", []
        )
        if isinstance(user_defined_methods, str):
            user_defined_methods = user_defined_methods.split(",")
            user_defined_methods = [method.strip() for method in user_defined_methods]

        user_defined_methods = set(user_defined_methods)
        skip_sig.update(user_defined_methods)

        # Enforce primitive-only payload always
        args = data.get("args", []).copy()
        kwargs = data.get("kwargs", {}).copy()
        _validate_primitive_payload(args, kwargs)

        # If this method is in the "skip-signature" list, do custom validation and stop
        if method in skip_sig:
            # Example: strict, explicit schema for get_attribute
            # - args: exactly 1 string attribute name
            # - kwargs: only {"default": <primitive>} allowed
            if method == "get_attribute":
                if len(args) != 1 or not isinstance(args[0], str) or not args[0]:
                    raise ValidationError(
                        "get_attribute requires a single non-empty string argument."
                    )
                disallowed_keys = set(kwargs) - {
                    "default",
                    "level",
                    "axis",
                    "on",
                    "suffixes",
                }
                if disallowed_keys:
                    raise ValidationError(
                        f"get_attribute does not accept kwargs: {sorted(disallowed_keys)}"
                    )
            return  # skip Python signature binding entirely

        # For all other methods, verify existence and argument binding
        is_callable_somewhere = False
        bad_arguments_everywhere = True

        for base_class in [BeliefsSeries, BeliefsDataFrame, Resampler, Grouper]:
            method_callable = getattr(base_class, method, None)
            if method_callable is None:
                continue

            # Check if the found method is callable
            if callable(method_callable):
                is_callable_somewhere = True
                try:
                    # Retrieve the method's signature for argument validation
                    sig = signature(method_callable)

                    # Insert the base class as the first argument to the method (self/cls context)
                    args.insert(0, BeliefsDataFrame)

                    # Bind the arguments to the method's signature for validation
                    sig.bind(*args, **kwargs)
                    bad_arguments_everywhere = (
                        False  # Arguments are valid if binding succeeds
                    )
                    break
                except TypeError:
                    # If binding raises a TypeError, the arguments are invalid
                    pass

        # Raise an error if the method is not callable in any of the base classes
        if not is_callable_somewhere:
            raise ValidationError(
                f"Method '{method}' not found on BeliefsSeries/BeliefsDataFrame/Resampler/Grouper."
            )
        # Raise an error if all arguments are invalid across all base classes
        if bad_arguments_everywhere:
            raise ValidationError(f"Bad arguments for method '{method}'.")


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
