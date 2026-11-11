"""JSON API token lifecycle backed by Flask-Security refresh trackers."""

import time

from flask import current_app
from flask_security.tokens import (
    new_refresh_tracker,
    get_refresh_token,
    verify_refresh_token,
    RefreshTokenErrors,
)
from flask_security.signals import refresh_tracker_revoked

from flexmeasures.data import db


def token_response(user, refresh_token: str) -> dict:
    """Report the effective lifetime, including a deployment's per-token expiry."""
    security = current_app.extensions["security"]
    access_token = user.get_auth_token()
    data, issued_at = security.remember_token_serializer.loads(
        access_token, return_timestamp=True
    )
    max_age = current_app.config["SECURITY_TOKEN_MAX_AGE"].total_seconds()
    deadlines = []
    if max_age:
        deadlines.append(issued_at.timestamp() + max_age)
    if data.get("exp"):
        deadlines.append(data["exp"])
    # None explicitly denotes a deployment configured with non-expiring tokens.
    expires_in = max(0, int(min(deadlines) - time.time())) if deadlines else None
    return {
        "auth_token": access_token,
        "user_id": user.id,
        "refresh-token": refresh_token,
        "expires-in": expires_in,
    }


def issue_refresh_token(user) -> dict:
    """Caller must hold the user lock and have verified their credentials."""
    _, refresh_token = new_refresh_tracker(user, name="api")
    payload = token_response(user, refresh_token)
    db.session.commit()
    return payload


def exchange_refresh_token(token: str, *, revoke: bool = False) -> tuple[dict, int]:
    """Validate, rotate or revoke within one transaction holding the family lock."""
    security = current_app.extensions["security"]
    datastore = security.datastore
    tracker, error, uid = verify_refresh_token(token)
    # Revocation is immediate. Upstream compares revoked_at < now, which permits
    # reuse at the same clock instant (or when worker clocks differ slightly).
    if tracker is not None and tracker.revoked_at is not None:
        error = RefreshTokenErrors.REVOKED
    user = (
        datastore.find_user(**{datastore.get_token_uniquifier_name(): uid})
        if uid
        else None
    )
    if tracker is not None and (revoke or error == RefreshTokenErrors.GEN_MISMATCH):
        datastore.revoke_refresh_tracker(tracker)
        refresh_tracker_revoked.send(
            current_app._get_current_object(),
            _async_wrapper=current_app.ensure_sync,
            user=user,
            refresh_tracker=tracker,
            refresh_errors=error,
        )
    if error or user is None or not user.active:
        # Commit replay revocation even though authentication failed.
        db.session.commit()
        return {
            "error": "invalid_refresh_token",
            "errors": ["Refresh token is invalid or expired. Authenticate again."],
        }, 401
    if revoke:
        db.session.commit()
        return {"revoked": True}, 200
    datastore.exchange_refresh_tracker(tracker)
    payload = token_response(user, get_refresh_token(tracker, user))
    db.session.commit()
    return payload, 200
