from marshmallow import Schema, fields, ValidationError, validates_schema, validate
from inspect import signature

from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.schemas.sources import DataSourceIdField

from flexmeasures.data.schemas import AwareDateTimeField, DurationField


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


class BeliefsSearchConfigSchema(Schema):
    """
    This schema implements the required fields to perform a TimedBeliefs search
    using the method flexmeasures.data.models.time_series:Sensor.search_beliefs
    """

    sensor = SensorIdField(required=True)

    event_starts_after = AwareDateTimeField()
    event_ends_before = AwareDateTimeField()

    belief_time = AwareDateTimeField()

    horizons_at_least = DurationField()
    horizons_at_most = DurationField()

    source = DataSourceIdField()

    source_types = fields.List(fields.Str())
    exclude_source_types = fields.List(fields.Str())
    most_recent_beliefs_only = fields.Boolean()
    most_recent_events_only = fields.Boolean()

    one_deterministic_belief_per_event = fields.Boolean()
    one_deterministic_belief_per_event_per_source = fields.Boolean()
    resolution = DurationField()
    sum_multiple = fields.Boolean()


class PandasReporterReporterConfigSchema(Schema):
    """
    This schema lists fields that can be used to describe sensors in the optimised portfolio

    Example:

    {
        "input_variables" : ["df1"],
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

    input_variables = fields.List(fields.Str(), required=True)
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
            (variable, BeliefsDataFrame) for variable in data.get("input_variables")
        )
        final_df_output = data.get("final_df_output")

        previous_df = None
        final_df_output_method = None

        for transformation in data.get("transformations"):

            df_input = transformation.get("df_input", previous_df)
            df_output = transformation.get("df_output", df_input)

            if df_output == final_df_output:
                final_df_output_method = transformation.get("method")

            if df_input not in fake_data:
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


class PandasReporterReportConfigSchema(Schema):
    input_sensors = fields.Dict(
        keys=fields.Str(),
        values=fields.Nested(BeliefsSearchConfigSchema()),
        required=True,
        validator=validate.Length(min=1),
    )

    start = AwareDateTimeField(required=False)
    end = AwareDateTimeField(required=False)

    resolution = DurationField(required=False)
    belief_time = AwareDateTimeField(required=False)

    @validates_schema
    def validate_time_parameters(self, data, **kwargs):
        """This method validates that all input sensors have start
        and end parameters available.
        """

        # it's enough to provide a common start and end
        if ("start" in data) and ("end" in data):
            return

        for alias, input_sensor in data.get("input_sensors").items():
            if ("event_starts_after" not in input_sensor) and ("start" not in data):
                raise ValidationError(
                    f"Start parameter not provided for sensor `{alias}` ({input_sensor})."
                )

            if ("event_ends_before" not in input_sensor) and ("end" not in data):
                raise ValidationError(
                    f"End parameter not provided for sensor `{alias}` ({input_sensor})."
                )
