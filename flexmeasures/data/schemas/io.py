from marshmallow import fields, Schema

from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.schemas import AwareDateTimeField, DurationField
from flexmeasures.data.schemas.sources import DataSourceIdField


class RequiredInput(Schema):
    name = fields.Str(required=True)


class Input(Schema):
    """
    This schema implements the required fields to perform a TimedBeliefs search
    using the method flexmeasures.data.models.time_series:TimedBelief.search_beliefs.

    It includes the field `name`, which is not part of the search query, for later reference of the belief.
    """

    name = fields.Str(required=False)

    sensor = SensorIdField(required=True)
    source = DataSourceIdField()

    event_starts_after = AwareDateTimeField()
    event_ends_before = AwareDateTimeField()

    belief_time = AwareDateTimeField()

    horizons_at_least = DurationField()
    horizons_at_most = DurationField()

    source_types = fields.List(fields.Str())
    exclude_source_types = fields.List(fields.Str())
    most_recent_beliefs_only = fields.Boolean()
    most_recent_events_only = fields.Boolean()

    one_deterministic_belief_per_event = fields.Boolean()
    one_deterministic_belief_per_event_per_source = fields.Boolean()
    resolution = DurationField()
    sum_multiple = fields.Boolean()


class Output(Schema):
    name = fields.Str(required=False)
    column = fields.Str(required=False)
    sensor = SensorIdField(required=True)


class RequiredOutput(Schema):
    name = fields.Str(required=True)
    column = fields.Str(required=False)
