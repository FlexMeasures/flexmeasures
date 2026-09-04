"""
Automations: recurring tasks (for now: forecasting) defined per asset.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import current_app
from pytz import all_timezones_set
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
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

    The recurrence is defined by a cron string, and the work to be done is defined
    by a data generator (e.g. a forecaster, linked through a data source) together
    with the parameters to call it with.
    """

    __tablename__ = "automation"

    SUPPORTED_TYPES = ["forecasts"]  # later also "schedules" and "reports"

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
    schedule_revision = db.Column(db.Integer, nullable=False, default=1)
    active = db.Column(db.Boolean, nullable=False, default=True)
    generator_id = db.Column(
        db.Integer, db.ForeignKey("data_source.id"), nullable=False
    )
    parameters = db.Column(MutableDict.as_mutable(JSONB), nullable=False, default={})

    asset = db.relationship(
        "GenericAsset",
        foreign_keys=[asset_id],
        backref=db.backref(
            "automations", lazy=True, cascade="all, delete-orphan", passive_deletes=True
        ),
    )
    generator = db.relationship("DataSource", foreign_keys=[generator_id])
    runs = db.relationship(
        "AutomationRun",
        back_populates="automation",
        lazy=True,
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="desc(AutomationRun.scheduled_at)",
    )

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


# A job intent counts as dispatched from this status onwards: it is in Redis, whatever became of it since.
AUTOMATION_RUN_JOB_QUEUED_OR_LATER = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "canceled",
)


class AutomationRun(db.Model):
    """Durable execution record for one scheduled automation occurrence."""

    __tablename__ = "automation_run"
    __table_args__ = (
        db.UniqueConstraint(
            "automation_id",
            "scheduled_at",
            "schedule_revision",
            name="automation_run_occurrence_uq",
        ),
        db.CheckConstraint(
            "dispatch_state IN ('pending', 'claimed', 'partially_queued', 'queued', 'failed')",
            name="automation_run_dispatch_state_ck",
        ),
        db.CheckConstraint(
            "execution_state IN ('pending', 'running', 'succeeded', 'failed', 'canceled')",
            name="automation_run_execution_state_ck",
        ),
    )

    id = db.Column(db.Integer, autoincrement=True, primary_key=True)
    automation_id = db.Column(
        db.Integer,
        db.ForeignKey("automation.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=server_now
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=server_now,
        onupdate=server_now,
    )
    scheduled_at = db.Column(db.DateTime(timezone=True), nullable=False)
    schedule_revision = db.Column(db.Integer, nullable=False)
    automation_type = db.Column(db.String(80), nullable=False)
    generator_id = db.Column(db.Integer, nullable=True)
    dispatch_state = db.Column(db.String(32), nullable=False, default="pending")
    execution_state = db.Column(db.String(32), nullable=False, default="pending")
    claim_owner = db.Column(db.String(128), nullable=True)
    claimed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    claim_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    first_enqueued_at = db.Column(db.DateTime(timezone=True), nullable=True)
    dispatch_completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    execution_started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    execution_completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_error_type = db.Column(db.String(160), nullable=True)
    last_error_message = db.Column(db.Text, nullable=True)
    parameters = db.Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)
    plan = db.Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)

    automation = db.relationship("Automation", back_populates="runs")
    attempts = db.relationship(
        "AutomationRunAttempt",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AutomationRunAttempt.attempt_no",
    )
    job_intents = db.relationship(
        "AutomationRunJob",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AutomationRunJob.logical_job_key",
    )

    @validates(
        "scheduled_at",
        "created_at",
        "updated_at",
        "claimed_at",
        "claim_expires_at",
        "first_enqueued_at",
        "dispatch_completed_at",
        "execution_started_at",
        "execution_completed_at",
    )
    def validate_datetime_is_aware(
        self, key: str, value: datetime | None
    ) -> datetime | None:
        """Store all automation run timestamps as timezone-aware UTC datetimes."""
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"Automation run {key} must be timezone-aware.")
        return value.astimezone(timezone.utc)

    @property
    def intended_job_count(self) -> int:
        """Return the number of persisted logical job intents."""
        return len(self.job_intents)

    @property
    def queued_job_count(self) -> int:
        """Return the number of logical jobs durably marked as queued or later."""
        return sum(
            1
            for intent in self.job_intents
            if intent.status in AUTOMATION_RUN_JOB_QUEUED_OR_LATER
        )


class AutomationRunAttempt(db.Model):
    """One durable attempt to claim and dispatch an automation run."""

    __tablename__ = "automation_run_attempt"
    __table_args__ = (
        db.UniqueConstraint(
            "run_id", "attempt_no", name="automation_run_attempt_no_uq"
        ),
    )

    id = db.Column(db.Integer, autoincrement=True, primary_key=True)
    run_id = db.Column(
        db.Integer,
        db.ForeignKey("automation_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_no = db.Column(db.Integer, nullable=False)
    owner = db.Column(db.String(128), nullable=False)
    started_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=server_now
    )
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    outcome = db.Column(db.String(64), nullable=True)
    queued_job_count = db.Column(db.Integer, nullable=False, default=0)
    error_type = db.Column(db.String(160), nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    run = db.relationship("AutomationRun", back_populates="attempts")

    @validates("started_at", "finished_at")
    def validate_datetime_is_aware(
        self, key: str, value: datetime | None
    ) -> datetime | None:
        """Store all automation run attempt timestamps as timezone-aware UTC datetimes."""
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"Automation run attempt {key} must be timezone-aware.")
        return value.astimezone(timezone.utc)


class AutomationRunJob(db.Model):
    """Durable outbox record for one logical job in an automation run."""

    __tablename__ = "automation_run_job"
    __table_args__ = (
        db.UniqueConstraint(
            "run_id", "logical_job_key", name="automation_run_job_logical_uq"
        ),
        db.UniqueConstraint("rq_job_id", name="automation_run_job_rq_job_uq"),
        db.CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'succeeded', 'failed', 'canceled')",
            name="automation_run_job_status_ck",
        ),
    )

    id = db.Column(db.Integer, autoincrement=True, primary_key=True)
    run_id = db.Column(
        db.Integer,
        db.ForeignKey("automation_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    logical_job_key = db.Column(db.String(128), nullable=False)
    rq_job_id = db.Column(db.String(191), nullable=False)
    queue = db.Column(db.String(80), nullable=False, default="forecasting")
    kind = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="pending")
    enqueued_at = db.Column(db.DateTime(timezone=True), nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_error_type = db.Column(db.String(160), nullable=True)
    last_error_message = db.Column(db.Text, nullable=True)
    depends_on = db.Column(MutableList.as_mutable(JSONB), nullable=False, default=list)
    payload = db.Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)

    run = db.relationship("AutomationRun", back_populates="job_intents")

    @validates("enqueued_at", "started_at", "finished_at")
    def validate_datetime_is_aware(
        self, key: str, value: datetime | None
    ) -> datetime | None:
        """Store all automation run job timestamps as timezone-aware UTC datetimes."""
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"Automation run job {key} must be timezone-aware.")
        return value.astimezone(timezone.utc)
