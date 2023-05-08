from marshmallow import Schema, fields, validate

from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.schemas.sources import DataSourceIdField

from flexmeasures.data.schemas import AwareDateTimeField, DurationField


class BeliefsSearchConfigSchema(Schema):
    """
    This schema implements the required fields to perform a TimeBeliefs search
    using the method flexmeasures.data.models.time_series:Sensor.search_beliefs
    """

    sensor = SensorIdField(required=True)
    alias = fields.Str()

    event_starts_after = AwareDateTimeField()
    event_ends_before = AwareDateTimeField()

    belief_time = AwareDateTimeField()

    horizons_at_least = DurationField()
    horizons_at_most = DurationField()

    source = DataSourceIdField()
    # user_source_ids: Optional[Union[int, List[int]]] = None,

    source_types = fields.List(fields.Str())
    exclude_source_types = fields.List(fields.Str())
    most_recent_beliefs_only = fields.Boolean()
    most_recent_events_only = fields.Boolean()

    one_deterministic_belief_per_event = fields.Boolean()
    one_deterministic_belief_per_event_per_source = fields.Boolean()
    resolution = DurationField()
    sum_multiple = fields.Boolean()


class ReporterConfigSchema(Schema):
    """
    This schema is used to validate Reporter class configurations (reporter_config).
    Inherit from this to extend this schema with your own parameters.
    """

    beliefs_search_config_schema = fields.List(
        fields.Nested(BeliefsSearchConfigSchema()),
        required=True,
        validator=validate.Length(min=1),
    )
