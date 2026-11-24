"""Persistent refresh-token families, using Flask-Security's rotation protocol."""

from flask_security import RefreshTrackerMixin
from sqlalchemy import event, inspect

from flexmeasures.data import db
from flexmeasures.data.models.user import User


class RefreshTokenTracker(db.Model, RefreshTrackerMixin):
    __tablename__ = "refresh_token_tracker"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("fm_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    refresh_family = db.Column(db.String(64), unique=True, nullable=False)
    gen = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(64), nullable=False)
    # Flask-Security's datetime_factory uses naive UTC datetimes.
    expires_at = db.Column(db.DateTime, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime)
    create_datetime = db.Column(
        db.DateTime, nullable=False, server_default=db.func.now()
    )
    user = db.relationship(
        User,
        backref=db.backref(
            "refresh_trackers",
            cascade="all, delete-orphan",
            order_by="RefreshTokenTracker.id",
        ),
    )


@event.listens_for(User, "after_update")
def revoke_refresh_tokens_on_identity_change(mapper, connection, user):
    """Do not revive refresh access when a disabled user is reactivated."""
    # The user UPDATE already holds the user-row lock. Token endpoints acquire
    # this same lock before touching families, so issuance cannot race this sweep.
    state = inspect(user)
    disabled = state.attrs.active.history.has_changes() and not user.active
    credentials_changed = any(
        state.attrs[field].history.has_changes()
        for field in ("password", "fs_uniquifier")
    )
    if disabled or credentials_changed:
        connection.execute(
            RefreshTokenTracker.__table__.update()
            .where(RefreshTokenTracker.user_id == user.id)
            .where(RefreshTokenTracker.revoked_at.is_(None))
            .values(revoked_at=db.func.timezone("UTC", db.func.now()))
        )
