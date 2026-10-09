from marshmallow import Schema, fields, pre_load, validate

from flexmeasures.data.schemas.sources import DataSourceIdField
from flexmeasures.data.schemas.account import AccountIdOrListField

from flexmeasures.data.schemas import AwareDateTimeField, DurationField
from flexmeasures.data.schemas.io import Input, Output


class ReporterConfigSchema(Schema):
    """
    This schema is used to validate Reporter class configurations (config).
    Inherit from this class to extend this schema with your own parameters.
    """

    pass


class ReporterParametersSchema(Schema):
    """
    This schema is used to validate the parameters to the method `compute` of
     the Reporter class.
    Inherit from this class to extend this schema with your own parameters.
    """

    input = fields.List(
        fields.Nested(Input()),
        required=True,
        validate=validate.Length(min=1),
    )

    output = fields.List(
        fields.Nested(Output()), required=True, validate=validate.Length(min=1)
    )

    start = AwareDateTimeField(required=True)
    end = AwareDateTimeField(required=True)

    resolution = DurationField(required=False)
    belief_time = AwareDateTimeField(required=False, data_key="prior")
    check_output_resolution = fields.Bool(required=False)
    belief_horizon = DurationField(required=False)

    @pre_load
    def accept_legacy_belief_time(self, data, **kwargs):
        """Accept "belief_time", the name report parameters used for "prior" up to v1.0.

        Where both are given, "prior" wins, unlike for other legacy aliases (see `SupportsLegacyFieldAliases`):
        a data generator merges the parameters of a new run into those it loaded for its previous run,
        so a stale "belief_time" left over from that load can meet the new run's "prior".
        """
        if not hasattr(data, "items") or "belief_time" not in data:
            return data
        data = dict(data)
        legacy_belief_time = data.pop("belief_time")
        data.setdefault("prior", legacy_belief_time)
        return data


class ReportTriggerSchema(Schema):
    """Validate the request envelope for a one-off reporting job.

    The selected reporter subsequently validates ``config`` and ``parameters``
    with its concrete configuration and parameter schemas.
    """

    reporter = fields.Str(required=True)
    config = fields.Dict(keys=fields.Str(), load_default=dict)
    parameters = fields.Dict(keys=fields.Str(), required=True)


class BeliefsSearchConfigSchema(Schema):
    """
    This schema implements the required fields to perform a TimedBeliefs search
    using the method flexmeasures.data.models.time_series:Sensor.search_beliefs
    """

    event_starts_after = AwareDateTimeField()
    event_ends_before = AwareDateTimeField()

    beliefs_before = AwareDateTimeField()
    beliefs_after = AwareDateTimeField()

    horizons_at_least = DurationField()
    horizons_at_most = DurationField()

    source = DataSourceIdField()
    source_account_ids = AccountIdOrListField()

    source_types = fields.List(fields.Str())
    exclude_source_types = fields.List(fields.Str())
    most_recent_beliefs_only = fields.Boolean()
    most_recent_events_only = fields.Boolean()

    one_deterministic_belief_per_event = fields.Boolean()
    one_deterministic_belief_per_event_per_source = fields.Boolean()
    resolution = DurationField()
    sum_multiple = fields.Boolean()


class StatusSchema(Schema):
    max_staleness = DurationField(required=True)
    max_future_staleness = DurationField(required=True)

    staleness_search = fields.Nested(BeliefsSearchConfigSchema(), required=True)
