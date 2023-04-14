from marshmallow import Schema, fields

from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.schemas.sources import DataSourceIdField


class TimeBeliefQueryConfigSchema(Schema):
    """
    This schema implements the required fields to perform a TimeBeliefs search
    using the method flexmeasures.data.models.time_series:TimedBelief.search
    """

    sensor = SensorIdField(required=True)

    event_starts_after = fields.DateTime()
    event_ends_before = fields.DateTime()

    beliefs_after = fields.DateTime()
    beliefs_before = fields.DateTime()

    horizons_at_least = fields.TimeDelta(precision="minutes")
    horizons_at_most = fields.TimeDelta(precision="minutes")

    source = DataSourceIdField()
    # user_source_ids: Optional[Union[int, List[int]]] = None,

    source_types = fields.List(fields.Str())
    exclude_source_types = fields.List(fields.Str())
    most_recent_beliefs_only = fields.Boolean()
    most_recent_events_only = fields.Boolean()

    one_deterministic_belief_per_event = fields.Boolean()
    one_deterministic_belief_per_event_per_source = fields.Boolean()
    resolution = fields.TimeDelta()
    sum_multiple = fields.Boolean()


class ReporterConfigSchema(Schema):
    """
    This schema is used to validate Reporter class configurations (reporter_config).
    Inherit from this to extend this schema with your own parameters.

    If the fields event_starts_after or event_ends_before are not present in `tb_query_config`
    they will look up in the fields `start` and `end`
    """

    tb_query_config = fields.List(
        fields.Nested(TimeBeliefQueryConfigSchema()), required=True
    )
    start = fields.DateTime()
    end = fields.DateTime()
