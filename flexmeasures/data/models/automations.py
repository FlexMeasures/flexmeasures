"""Automations: recurring forecasting or scheduling tasks defined per asset."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import current_app
from pytz import all_timezones_set
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import validates

from flexmeasures.auth.policy import AuthModelMixin
from flexmeasures.data import db
from flexmeasures.utils.time_utils import server_now


def get_default_automation_timezone() -> str:
    """Return the timezone to snapshot when an automation is created."""
    timezone_name = current_app.config.get("FLEXMEASURES_TIMEZONE", "UTC")
    if timezone_name not in all_timezones_set:
        raise ValueError(f"Timezone '{timezone_name}' does not exist.")
    return timezone_name


def get_initial_cursor() -> datetime:
    """Return a cursor which keeps the automation's creation minute eligible."""
    return server_now().astimezone(timezone.utc).replace(
        second=0, microsecond=0
    ) - timedelta(minutes=1)


class Automation(db.Model, AuthModelMixin):
    """A recurring task on an asset, such as computing forecasts.

    The recurrence is defined by a cron string. Forecast automations use a data
    generator (e.g. a forecaster linked through a data source), while schedule
    automations use only their stored parameters.
    """

    __tablename__ = "automation"
    __table_args__ = (
        db.CheckConstraint(
            "type != 'forecasts' OR generator_id IS NOT NULL",
            name="forecast_generator",
        ),
    )

    SUPPORTED_TYPES = ["forecasts", "schedules"]  # later also "reports"

    id = db.Column(db.Integer, autoincrement=True, primary_key=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=server_now
    )
    asset_id = db.Column(
        db.Integer,
        db.ForeignKey("generic_asset.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type = db.Column(db.String(80), nullable=False, default="forecasts")
    name = db.Column(db.String(80), nullable=False)
    cronstr = db.Column(db.String(80), nullable=False)
    timezone = db.Column(
        db.String(64), nullable=False, default=get_default_automation_timezone
    )
    # The scheduled time of the most recent run this automation committed to.
    # Runs at or before it are never queued again, which is what makes catch-up after downtime queue only the latest missed run.
    # It advances just before queueing, so it records that a run was claimed, not that queueing or the forecast itself succeeded.
    cursor = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=get_initial_cursor,
    )
    active = db.Column(db.Boolean, nullable=False, default=True)
    generator_id = db.Column(db.Integer, db.ForeignKey("data_source.id"), nullable=True)
    parameters = db.Column(MutableDict.as_mutable(JSONB), nullable=False, default={})

    asset = db.relationship(
        "GenericAsset",
        foreign_keys=[asset_id],
        backref=db.backref(
            "automations", lazy=True, cascade="all, delete-orphan", passive_deletes=True
        ),
    )
    generator = db.relationship("DataSource", foreign_keys=[generator_id])

    @validates("timezone")
    def validate_timezone(self, key: str, timezone: str) -> str:
        """Require an exact timezone name from the IANA timezone database."""
        if timezone not in all_timezones_set:
            raise ValueError(f"Timezone '{timezone}' does not exist.")
        return timezone

    def __acl__(self):
        """
        Whoever can read the asset can read its automations.
        Updating and deleting automations is allowed for whoever can delete
        the asset (i.e. account admins and consultants).
        """
        if self.asset is None:
            return {}
        asset_acl = self.asset.__acl__()
        return {
            "read": asset_acl["read"],
            "update": asset_acl["delete"],
            "delete": asset_acl["delete"],
        }

    def __repr__(self):
        return "<Automation %s: %r (%s on asset %s, %s)>" % (
            self.id,
            self.name,
            self.type,
            self.asset_id,
            "active" if self.active else "inactive",
        )

    @property
    def input_sensors(self) -> list:
        """The sensors that this automation reads data from on each run, as far as they can be worked out.

        Reports no sensors if they cannot be, so do not use this to decide whether something is permitted;
        see `resolve_automation_sensors` for that.
        """
        from flexmeasures.data.services.automations import get_automation_sensors

        return get_automation_sensors(self)["input_sensors"]

    @property
    def output_sensors(self) -> list:
        """The sensors that this automation writes data to on each run. See `input_sensors`."""
        from flexmeasures.data.services.automations import get_automation_sensors

        return get_automation_sensors(self)["output_sensors"]
