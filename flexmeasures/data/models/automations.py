"""
Automations: recurring tasks (for now: forecasting) defined per asset.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict

from flexmeasures.auth.policy import (
    AuthModelMixin,
    ACCOUNT_ADMIN_ROLE,
    CONSULTANT_ROLE,
)
from flexmeasures.data import db
from flexmeasures.utils.time_utils import server_now


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
    )
    type = db.Column(db.String(80), nullable=False, default="forecasts")
    name = db.Column(db.String(80), nullable=False)
    cronstr = db.Column(db.String(80), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    generator_id = db.Column(
        db.Integer, db.ForeignKey("data_source.id", ondelete="CASCADE"), nullable=True
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

    def __acl__(self):
        """
        Whoever can read the asset can read its automations.
        Creating, updating and deleting automations is allowed for
        account admins and consultants.
        """
        account_id = self.asset.account_id if self.asset is not None else None
        owner = self.asset.owner if self.asset is not None else None
        admin_or_consultant = [
            (f"account:{account_id}", f"role:{ACCOUNT_ADMIN_ROLE}"),
            (
                (
                    f"account:{owner.consultancy_account_id}",
                    f"role:{CONSULTANT_ROLE}",
                )
                if owner is not None
                else ()
            ),
        ]
        return {
            "read": self.asset.__acl__()["read"] if self.asset is not None else [],
            "update": admin_or_consultant,
            "delete": admin_or_consultant,
        }

    def __repr__(self):
        return "<Automation %s: %r (%s on asset %s, %s)>" % (
            self.id,
            self.name,
            self.type,
            self.asset_id,
            "active" if self.active else "inactive",
        )
