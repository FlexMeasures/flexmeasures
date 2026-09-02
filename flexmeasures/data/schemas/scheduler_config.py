"""The schema describing a scheduler's configuration.

This lives apart from the rest of the scheduling schemas because ``flexmeasures.data.models.planning`` imports it,
and that module is imported while the ``flexmeasures`` package itself is still initialising.
"""

from __future__ import annotations

from marshmallow import Schema, fields


class SchedulerConfigSchema(Schema):
    """The configuration of a scheduler: which asset it schedules, and the flex config it uses.

    Together with the scheduler's class and version, this is what tells one scheduler data source from another,
    so that a schedule can be traced back to the configuration it was computed under.
    Timing fields are deliberately absent: start, end, resolution and belief time differ from run to run,
    and are the scheduler's parameters rather than its configuration.

    The flex config is kept in its serialized form, as the trigger message and the asset tree spell it,
    because that is the form every scheduler shares.
    Deserialized flex configs hold sensors, quantities and time series, which each scheduler resolves in its own way.
    """

    asset = fields.Integer(
        required=False,
        allow_none=True,
        metadata=dict(
            description="ID of the asset (or of the sensor's asset) that this scheduler schedules.",
        ),
    )
    flex_model = fields.Raw(
        attribute="flex-model",
        data_key="flex-model",
        required=False,
        allow_none=True,
        metadata=dict(
            description="The flex-model the scheduler uses, after merging the trigger message with what the asset tree stores.",
        ),
    )
    flex_context = fields.Raw(
        attribute="flex-context",
        data_key="flex-context",
        required=False,
        allow_none=True,
        metadata=dict(
            description="The flex-context the scheduler uses, after merging the trigger message with what the asset tree stores.",
        ),
    )
