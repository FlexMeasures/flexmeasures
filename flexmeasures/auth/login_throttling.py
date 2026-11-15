"""
Limit how often a user account can be guessed at.

Each failed attempt to authenticate as a user (a wrong password on the login form or on /api/requestAuthToken,
or a wrong two-factor code) is counted against that user, in a fixed window (``FLEXMEASURES_AUTHENTICATION_FAILURE_LIMIT``).
Once the user's count is used up, further attempts for that user are refused with 429 until the window ends,
*before* the credentials are checked, so the answer does not tell whether the password was right.
A successful login clears the count.

Password recovery requests (the "forgot password" form) are counted per email address,
whether or not a user with that address exists (``FLEXMEASURES_PASSWORD_RECOVERY_LIMIT``),
so the form cannot be used to flood someone's inbox.

We count per user rather than per IP address: behind a reverse proxy, every client has the proxy's address,
so a limit per address would let one client lock everyone out of the login form.
The counts live in the rate limiter's storage (see flexmeasures.api.common.rate_limiting).
"""

from __future__ import annotations

from flask import Flask, current_app, jsonify, make_response, request, session
from limits import parse
from sqlalchemy import func, select

from flexmeasures.data import db

FAILURE_SCOPE = "authentication-failures"
RECOVERY_SCOPE = "password-recovery"

# Endpoints at which a user's credentials are checked, and the endpoint at which recovery is requested
CREDENTIAL_ENDPOINTS = (
    "security.login",
    "security.two_factor_token_validation",
    "flexmeasures_api.request_auth_token",
)
RECOVERY_ENDPOINT = "security.forgot_password"


def _strategy():
    """The rate limiter's counting strategy, or None if rate limiting is switched off."""
    from flexmeasures.api.common.rate_limiting import limiter

    if not limiter.enabled:
        return None
    try:
        return limiter.limiter
    except AssertionError:  # not initialised
        return None


def _identifiers(scope: str, key: str) -> list[str]:
    from flexmeasures.api.common.rate_limiting import limiter

    prefix = [limiter._key_prefix] if limiter._key_prefix else []
    return [*prefix, scope, key]


def _user_key(user_id: int) -> str:
    return f"user:{user_id}"


def _failure_limit():
    return parse(current_app.config["FLEXMEASURES_AUTHENTICATION_FAILURE_LIMIT"])


def _recovery_limit():
    return parse(current_app.config["FLEXMEASURES_PASSWORD_RECOVERY_LIMIT"])


def _submitted_email() -> str | None:
    """The email address given in a form or JSON body, if any."""
    email = None
    if request.is_json:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            email = payload.get("email")
    else:
        email = request.form.get("email")
    if not isinstance(email, str) or not email.strip():
        return None
    return email.strip().lower()


def _user_id_of_attempt() -> int | None:
    """Which user the current request tries to authenticate as, if we can tell."""
    from flexmeasures.data.models.user import User

    if request.endpoint == "security.two_factor_token_validation":
        fs_uniquifier = session.get("tf_user_id")
        if not fs_uniquifier:
            return None
        return db.session.execute(
            select(User.id).filter_by(fs_uniquifier=fs_uniquifier)
        ).scalar_one_or_none()
    email = _submitted_email()
    if email is None:
        return None
    return db.session.execute(
        select(User.id).where(func.lower(User.email) == email)
    ).scalar_one_or_none()


def _too_many_attempts_response(message: str):
    if request.is_json or request.path.startswith("/api/"):
        response = jsonify({"status": "TOO_MANY_REQUESTS", "message": message})
    else:
        response = make_response(message)
        response.mimetype = "text/plain"
    response.status_code = 429
    return response


def refuse_attempts_beyond_limit():
    """Refuse authentication attempts for a user who used up their failed attempts, and count recovery requests."""
    if request.method != "POST":
        return None
    endpoint = request.endpoint
    if endpoint not in CREDENTIAL_ENDPOINTS and endpoint != RECOVERY_ENDPOINT:
        return None
    strategy = _strategy()
    if strategy is None:
        return None
    try:
        if endpoint == RECOVERY_ENDPOINT:
            email = _submitted_email()
            if email is None:
                return None  # the form will say what is missing
            if not strategy.hit(
                _recovery_limit(), *_identifiers(RECOVERY_SCOPE, f"email:{email}")
            ):
                current_app.logger.warning(
                    "Refused a password recovery request: too many requests for this email address recently."
                )
                return _too_many_attempts_response(
                    "Too many password recovery requests. Please try again later."
                )
            return None
        user_id = _user_id_of_attempt()
        if user_id is None:
            return None
        if not strategy.test(
            _failure_limit(), *_identifiers(FAILURE_SCOPE, _user_key(user_id))
        ):
            current_app.logger.warning(
                f"Refused an authentication attempt for user {user_id}: too many failed attempts recently ({request.endpoint})."
            )
            return _too_many_attempts_response(
                "Too many failed attempts to log in. Please try again later."
            )
    except (
        Exception
    ) as exc:  # the limiter's storage may be unreachable; do not lock everyone out
        current_app.logger.warning(
            f"Could not check the authentication attempt limit: {exc}"
        )
    return None


def count_failed_authentication(sender, user=None, **kwargs):
    """Count a failed authentication against the user (connected to Flask-Security's user_failed_authn signal)."""
    strategy = _strategy()
    if strategy is None or user is None:
        return
    try:
        strategy.hit(_failure_limit(), *_identifiers(FAILURE_SCOPE, _user_key(user.id)))
    except Exception as exc:
        current_app.logger.warning(
            f"Could not count a failed authentication attempt: {exc}"
        )


def clear_failed_authentications(sender, user=None, **kwargs):
    """Start a user's count afresh once they logged in (connected to Flask-Login's user_logged_in signal)."""
    strategy = _strategy()
    if strategy is None or user is None:
        return
    try:
        strategy.clear(
            _failure_limit(), *_identifiers(FAILURE_SCOPE, _user_key(user.id))
        )
    except Exception as exc:
        current_app.logger.warning(
            f"Could not clear the failed authentication attempts of user {user.id}: {exc}"
        )


def register_at(app: Flask):
    from flask_login import user_logged_in
    from flask_security.signals import user_failed_authn

    app.before_request(refuse_attempts_beyond_limit)
    user_failed_authn.connect(count_failed_authentication, app)
    user_logged_in.connect(clear_failed_authentications, app)
