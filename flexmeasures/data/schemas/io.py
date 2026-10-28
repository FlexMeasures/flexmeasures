from marshmallow import (
    fields,
    validate,
    Schema,
    post_load,
    post_dump,
    validates_schema,
    ValidationError,
)

from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.schemas import AwareDateTimeField, DurationField
from flexmeasures.data.schemas.sources import DataSourceIdField
from flexmeasures.data.schemas.account import AccountIdOrListField
from flexmeasures.utils.bound_utils import bound_validation_errors
from flask import current_app


class RequiredInput(Schema):
    name = fields.Str(required=True)
    unit = fields.Str(required=False)


class Input(Schema):
    """
    This schema implements the required fields to perform a TimedBeliefs search
    using the method flexmeasures.data.models.time_series:TimedBelief.search_beliefs.

    It includes the field `name`, which is not part of the search query, for later reference of the belief.
    """

    name = fields.Str(required=False)

    sensor = SensorIdField(required=True)
    source = DataSourceIdField()
    sources = fields.List(DataSourceIdField())

    event_starts_after = AwareDateTimeField()
    event_ends_before = AwareDateTimeField()

    belief_time = AwareDateTimeField()
    beliefs_after = AwareDateTimeField()

    horizons_at_least = DurationField()
    horizons_at_most = DurationField()

    user_source_ids = fields.List(DataSourceIdField())
    source_account_ids = AccountIdOrListField()
    source_types = fields.List(fields.Str())
    exclude_source_types = fields.List(fields.Str())
    most_recent_beliefs_only = fields.Boolean()
    most_recent_events_only = fields.Boolean()

    use_latest_version_per_event = fields.Boolean()
    one_deterministic_belief_per_event = fields.Boolean()
    one_deterministic_belief_per_event_per_source = fields.Boolean()
    most_recent_only = fields.Boolean()
    resolution = DurationField()
    sum_multiple = fields.Boolean()

    lower = fields.Raw(
        required=False,
        allow_none=True,
        metadata=dict(
            description="Optional lower bound for the readings taken from this sensor, applied before the report is computed, so that a sensor with implausible readings can be reported on without correcting it at the source. Unitless values are interpreted in the sensor's own unit.",
            example="0 kW",
        ),
    )
    upper = fields.Raw(
        required=False,
        allow_none=True,
        metadata=dict(
            description="Optional upper bound for the readings taken from this sensor, applied before the report is computed. Unitless values are interpreted in the sensor's own unit.",
            example="20 kW",
        ),
    )
    snap = fields.Dict(
        keys=fields.Raw(),
        values=fields.List(fields.Raw(), validate=validate.Length(equal=2)),
        required=False,
        allow_none=True,
        metadata=dict(
            description="Optional mapping from snap targets to [first, second] intervals, applied to the readings taken from this sensor. Readings inside an interval are replaced by the target, which must lie within the interval. The first bound is inclusive and the second exclusive.",
            example={"0 kW": ["0 kW", "0.5 kW"]},
        ),
    )

    @validates_schema
    def validate_bounds(self, data: dict, **kwargs):
        """Refuse a bound this input's sensor cannot take, while the report is still being set up.

        The sensor is known here, so an incompatible unit, a snap target outside its interval and a lower bound above the upper one are caught before any data is read.
        """
        sensor = data.get("sensor")
        errors = bound_validation_errors(
            data.get("lower"),
            data.get("upper"),
            data.get("snap"),
            sensor_unit=sensor.unit if sensor is not None else None,
            label=(
                f"bounds on sensor {sensor.name} (ID: {sensor.id})"
                if sensor is not None
                else "input bounds"
            ),
        )
        if errors:
            raise ValidationError(errors)

    def print_source_deprecation_warning(self, data):
        if "source" in data:
            current_app.logger.warning(
                "`source` field to be deprecated in v0.17.0. Please, use `sources` instead"
            )

    @post_load
    def post_load_deprecation_warning_source(self, data: dict, **kawrgs) -> dict:
        self.print_source_deprecation_warning(data)
        return data

    @post_dump
    def post_dump_deprecation_warning_source(self, data: dict, **kwargs) -> dict:
        self.print_source_deprecation_warning(data)
        return data


class Output(Schema):
    name = fields.Str(required=False)
    column = fields.Str(required=False)
    sensor = SensorIdField(required=True)


class RequiredOutput(Schema):
    name = fields.Str(required=True)
    column = fields.Str(required=False)
    unit = fields.Str(required=False)
