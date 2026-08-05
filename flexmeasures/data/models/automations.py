"""Automations: recurring forecasting or scheduling tasks defined per asset."""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict

from flexmeasures.auth.policy import AuthModelMixin
from flexmeasures.data import db
from flexmeasures.utils.time_utils import server_now


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
    )
    type = db.Column(db.String(80), nullable=False, default="forecasts")
    name = db.Column(db.String(80), nullable=False)
    cronstr = db.Column(db.String(80), nullable=False)
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
