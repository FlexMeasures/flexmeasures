"""Store refresh-token families without loading a user's full tracker collection."""

from uuid import uuid4

from flask import current_app
from flask_security import SQLAlchemySessionUserDatastore
from sqlalchemy import delete, or_, select

from flexmeasures.data.models.refresh_tokens import RefreshTokenTracker
from flexmeasures.data.models.user import User


class FlexMeasuresUserDatastore(SQLAlchemySessionUserDatastore):
    def _delete_refresh_trackers(self, user, *conditions):
        """Delete matching trackers for one user and invalidate any loaded collection."""
        self.db.session.execute(
            delete(RefreshTokenTracker)
            .where(RefreshTokenTracker.user_id == user.id, *conditions)
            .execution_options(synchronize_session="fetch")
        )
        self.db.session.expire(user, ["refresh_trackers"])

    def cleanup_refresh_trackers(self, user, expired=True, revoked=False):
        """Preserve Flask-Security's cleanup options without hydrating every tracker."""
        self.put(user)
        # Flask-Security may call this outside the API; keep the same user-before-family lock order there too.
        with self.db.session.no_autoflush:
            if user.id is None:
                return
            self.db.session.scalar(
                select(User.id).where(User.id == user.id).with_for_update()
            )
        now = current_app.extensions["security"].datetime_factory()
        conditions = []
        if expired:
            conditions.append(RefreshTokenTracker.expires_at < now)
        if revoked:
            conditions.append(RefreshTokenTracker.revoked_at.is_not(None))
        if conditions:
            self._delete_refresh_trackers(user, or_(*conditions))

    def cleanup_inactive_api_refresh_trackers(self, user):
        """Remove only API families which can no longer be refreshed."""
        now = current_app.extensions["security"].datetime_factory()
        idle_before = now - current_app.config["SECURITY_REFRESH_TOKEN_MAX_IDLE"]
        self._delete_refresh_trackers(
            user,
            RefreshTokenTracker.name == "api",
            or_(
                RefreshTokenTracker.revoked_at.is_not(None),
                RefreshTokenTracker.expires_at < now,
                RefreshTokenTracker.last_used_at < idle_before,
            ),
        )

    def create_refresh_tracker(self, user, name, expires_at, **kwargs):
        """Create a tracker without loading the user's other families."""
        tracker = RefreshTokenTracker(
            user=user,
            gen=1,
            name=name,
            expires_at=expires_at,
            refresh_family=uuid4().hex,
            last_used_at=current_app.extensions["security"].datetime_factory(),
            **kwargs,
        )
        self.put(tracker)
        return tracker

    def find_refresh_tracker(self, refresh_family: str) -> RefreshTokenTracker | None:
        user_id = self.db.session.scalar(
            select(RefreshTokenTracker.user_id).where(
                RefreshTokenTracker.refresh_family == refresh_family
            )
        )
        if user_id is None:
            return None
        # Always lock user before family, matching credential changes and issuance.
        self.db.session.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        # Hold the lock until the endpoint commits, including reuse revocation.
        # Refresh ORM state too: another transaction may have rotated this family.
        return self.db.session.scalar(
            select(RefreshTokenTracker)
            .where(RefreshTokenTracker.refresh_family == refresh_family)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
