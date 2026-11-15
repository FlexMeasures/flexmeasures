"""
Log authentication events: logins (succeeded and failed), two-factor failures, logouts and token requests.

Each line starts with "Authentication event:", says what happened and to which user (by id),
and gives the client's IP address as the app sees it (behind a reverse proxy, that is the proxy's,
unless the proxy's forwarded headers are applied). Passwords, codes and tokens are never logged.
An email address that matches no user is logged as a short hash, so that repeated attempts on one
address can be told apart without writing the guessed addresses to the log.
"""

from __future__ import annotations

import hashlib

from flask import Flask, current_app, has_request_context, request


def _client() -> str:
    if not has_request_context():
        return "no request"
    return f"{request.remote_addr} on {request.endpoint}"


def email_fingerprint(email: str) -> str:
    """A short, stable hash of an email address, for log lines about addresses that match no user."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:12]


def log_authentication_event(message: str, failed: bool = False):
    log = current_app.logger.warning if failed else current_app.logger.info
    log(f"Authentication event: {message} (client {_client()}).")


def log_successful_login(sender, user=None, authn_via=None, **kwargs):
    """Connected to Flask-Security's user_authenticated signal."""
    if user is None:
        return
    via = ", ".join(authn_via or []) or "unknown method"
    log_authentication_event(f"user {user.id} logged in (via {via})")


def log_failed_authentication(sender, user=None, auth_type=None, tfa=False, **kwargs):
    """Connected to Flask-Security's user_failed_authn signal, which is sent for a known user's wrong password or code."""
    if user is None:
        return
    what = "two-factor code" if tfa else (auth_type or "credential")
    log_authentication_event(
        f"failed {what} for user {user.id}",
        failed=True,
    )


def log_logout(sender, user=None, **kwargs):
    """Connected to Flask-Login's user_logged_out signal."""
    if user is None or not getattr(user, "is_authenticated", False):
        return
    log_authentication_event(f"user {user.id} logged out")


def register_at(app: Flask):
    from flask_login import user_logged_out
    from flask_security.signals import user_authenticated, user_failed_authn

    user_authenticated.connect(log_successful_login, app)
    user_failed_authn.connect(log_failed_authentication, app)
    user_logged_out.connect(log_logout, app)
