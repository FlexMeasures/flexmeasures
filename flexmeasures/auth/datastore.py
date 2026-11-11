"""Serialize validation and rotation of a refresh-token family."""

from flask_security import SQLAlchemySessionUserDatastore
from sqlalchemy import select

from flexmeasures.data.models.refresh_tokens import RefreshTokenTracker
from flexmeasures.data.models.user import User


class FlexMeasuresUserDatastore(SQLAlchemySessionUserDatastore):
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
