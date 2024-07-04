from marshmallow import fields, Schema, post_load, post_dump

from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.schemas import AwareDateTimeField, DurationField
from flexmeasures.data.schemas.sources import DataSourceIdField
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
