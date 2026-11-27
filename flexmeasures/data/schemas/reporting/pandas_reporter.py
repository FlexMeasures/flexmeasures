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
DEFAULT_SKIP_SIGNATURE_METHODS = {"get_attribute"}

# The properties a transformation may read.
# Pandas data attributes, and (as in PR #1669) the sensor of a BeliefsDataFrame and that sensor's asset,
# so that a pseudo-method like get_attribute can read their attributes.
# Which property may be read from which kind of object is checked again when the transformations run.
PANDAS_TRANSFORMATION_PROPERTIES = frozenset(
    {
        *("index", "columns", "T", "values", "empty", "shape", "size", "ndim"),
        *("dtypes", "dtype", "name", "event_starts", "event_ends"),
    }
)
ALLOWED_TRANSFORMATION_PROPERTIES = PANDAS_TRANSFORMATION_PROPERTIES | {
    "sensor",
    "generic_asset",
}

# The pandas methods a transformation may call, besides the pseudo-methods above.
# A reporter config comes from users (report triggers and automations),
# so methods that write files (to_*) or evaluate expressions (eval, query) are left out,
# as is pipe, which calls any function. Methods that call other methods named by strings
# (see FUNCTION_NAME_METHODS) are allowed only with names from this list.
ALLOWED_TRANSFORMATION_METHODS = frozenset(
    {
        # arithmetic and rounding
        *("add", "radd", "sub", "subtract", "rsub", "mul", "multiply", "rmul"),
        *("div", "divide", "truediv", "rdiv", "rtruediv", "floordiv", "rfloordiv"),
        *("mod", "rmod", "pow", "rpow", "abs", "round", "clip", "dot"),
        # comparisons, masks and missing values
        *("gt", "ge", "lt", "le", "eq", "ne", "between", "isin"),
        *("where", "mask", "isna", "isnull", "notna", "notnull"),
        *("fillna", "ffill", "bfill", "dropna", "interpolate", "replace"),
        # aggregations
        *("sum", "mean", "median", "min", "max", "std", "var", "sem", "prod"),
        *("count", "nunique", "quantile", "idxmax", "idxmin", "first", "last"),
        *("size", "any", "all", "cumsum", "cumprod", "cummax", "cummin"),
        # resampling, grouping and windows
        *("resample", "resample_events", "asfreq", "nearest", "groupby", "rolling"),
        *("expanding", "ewm", "shift", "diff", "pct_change"),
        # selection and reshaping
        *("copy", "head", "tail", "xs", "droplevel", "drop", "drop_duplicates"),
        *("merge", "join", "combine_first", "align", "reindex", "reindex_like"),
        *("reset_index", "set_index", "sort_index", "sort_values"),
        *("rename", "rename_axis"),
        *("astype", "tz_convert", "tz_localize", "stack", "unstack", "squeeze"),
        *("to_frame", "convert_index_from"),
        # calling the methods above by name, such as agg(["min", "max"]) (see FUNCTION_NAME_METHODS)
        *("apply", "aggregate", "agg", "transform"),
    }
)

# Methods that call the functions named in their first argument (func, or arg for Resampler.transform).
# They may only name methods from ALLOWED_TRANSFORMATION_METHODS, other than these methods themselves:
# a name, a list of names, or a dict of column to a name or a list of names.
FUNCTION_NAME_METHODS = frozenset({"apply", "aggregate", "agg", "transform"})
FUNCTION_NAME_ARGUMENTS = ("func", "arg")


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


def _refuse_unlisted_method(method: str, skip_sig: set[str]):
    """Refuse a method that is neither an allowed pandas transformation nor a pseudo-method the host trusts."""
    if method not in ALLOWED_TRANSFORMATION_METHODS and method not in skip_sig:
        raise ValidationError(
            f"Method '{method}' cannot be used in a transformation.",
            field_name="method",
        )


def _refuse_unlisted_function_names(method: str, args: list, kwargs: dict):
    """Refuse a method that calls functions by name, unless it names only allowed methods.

    For example, {"method": "agg", "args": [["min", "max"]]} or {"method": "agg", "args": [{"a": "sum"}]} is fine,
    while {"method": "apply", "args": ["to_csv"]} is not.
    """
    named = [kwargs[key] for key in FUNCTION_NAME_ARGUMENTS if key in kwargs]
    if args:
        named.insert(0, args[0])
    if len(named) != 1:
        raise ValidationError(
            f"Method '{method}' needs exactly one function name, list of function names or dict of column to function names, as its first argument.",
            field_name="args",
        )
    functions = named[0]
    if isinstance(functions, dict):
        names = []
        for column_functions in functions.values():
            if isinstance(column_functions, list):
                names.extend(column_functions)
            else:
                names.append(column_functions)
    elif isinstance(functions, list):
        names = functions
    else:
        names = [functions]
    for name in names:
        if (
            not isinstance(name, str)
            or name not in ALLOWED_TRANSFORMATION_METHODS
            or name in FUNCTION_NAME_METHODS
        ):
            raise ValidationError(
                f"Method '{method}' cannot call {name!r}: only names of methods that can be used in a transformation are allowed.",
                field_name="args",
            )


def _validate_pseudo_method_payload(method: str, args: list, kwargs: dict):
    """Custom validation for pseudo-methods, which skip Python signature binding."""
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


def pseudo_methods() -> set[str]:
    """The pseudo-methods the host trusts (FLEXMEASURES_REPORTER_VALIDATION_SKIP_METHODS), such as get_attribute."""
    skip_sig = set(DEFAULT_SKIP_SIGNATURE_METHODS)

    user_defined_methods = app.config.get(
        "FLEXMEASURES_REPORTER_VALIDATION_SKIP_METHODS", []
    )
    if isinstance(user_defined_methods, str):
        user_defined_methods = user_defined_methods.split(",")
        user_defined_methods = [method.strip() for method in user_defined_methods]

    user_defined_methods = set(user_defined_methods)
    skip_sig.update(user_defined_methods)

    return skip_sig


class Transformation(Schema):

    df_input = fields.Str()
    df_output = fields.Str()

    method = fields.Str(required=False)
    _property = fields.Str(required=False, data_key="property")
    args = fields.List(fields.Raw())
    kwargs = fields.Dict()
    skip_if_empty = fields.Bool()

    def _update_signature_methods(self):
        return pseudo_methods()

    @validates_schema
    def validate_method_or_property(self, data, **kwargs):
        """Exactly one of 'method' or 'property' must be provided.
        Additionally, 'args'/'kwargs' are only allowed when 'method' is provided.
        """
        method = data.get("method")
        prop = data.get("_property")  # internal name for data_key="property"

        # Enforce exactly-one rule
        if bool(method) == bool(prop):
            # both set or both missing
            raise ValidationError(
                "Exactly one of 'method' or 'property' must be provided.",
                field_name="method",
            )

        # If no method (i.e., using 'property'), args/kwargs must be empty/absent
        if not method:
            if data.get("args"):
                raise ValidationError(
                    "'args' can only be set when 'method' is provided.",
                    field_name="args",
                )
            if data.get("kwargs"):
                raise ValidationError(
                    "'kwargs' can only be set when 'method' is provided.",
                    field_name="kwargs",
                )

    @validates_schema
    def validate_property(self, data, **kwargs):
        """Only listed data attributes may be read: not private ones, not methods, which would bypass the method allow-list,
        and not attributes leading to other objects, such as a sensor's account."""
        prop = data.get("_property")
        if prop is None:
            return
        if (
            prop not in ALLOWED_TRANSFORMATION_PROPERTIES
            or prop.startswith("_")
            or any(
                callable(getattr(base_class, prop, None))
                for base_class in [BeliefsSeries, BeliefsDataFrame, Resampler, Grouper]
            )
        ):
            raise ValidationError(
                f"Property '{prop}' cannot be used in a transformation.",
                field_name="property",
            )

    @validates_schema
    def validate_method_call(self, data, **kwargs):
        """Validates the method name and its arguments against a set of base classes.

        This validation ensures that the provided method exists in one of the
        specified base classes (`BeliefsSeries`, `BeliefsDataFrame`, `Resampler`, `Grouper`)
        and that the provided arguments (`args` and `kwargs`) are valid for the method's
        signature.

        :param data:        A dictionary containing the method name (`method`) and optionally the method arguments (`args` as a list and `kwargs` as a dictionary).
        :param kwargs:      Additional keyword arguments passed by the validation framework.
        :raises ValidationError: If the method is not callable in any of the base classes or if the provided arguments do not match the method signature.
        """

        method = data.get("method")
        if method is None:
            return

        # Enforce primitive-only payload always
        args = data.get("args", []).copy()
        kwargs = data.get("kwargs", {}).copy()
        _validate_primitive_payload(args, kwargs)

        skip_sig = self._update_signature_methods()

        _refuse_unlisted_method(method, skip_sig)

        # If this method is in the "skip-signature" list, do custom validation and stop
        if method in skip_sig:
            _validate_pseudo_method_payload(method, args, kwargs)
            return  # skip Python signature binding entirely

        if method in FUNCTION_NAME_METHODS:
            _refuse_unlisted_function_names(method, args, kwargs)

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
    transformations = fields.List(fields.Nested(Transformation()), required=True)

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
                    f"Cannot find final output `{_output}` DataFrame among the resulting DataFrames."
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
