"""
Limit how often an account can be guessed at.

Every attempt to authenticate (a password on the login form or on /api/requestAuthToken, or a two-factor code)
is counted *before* the credentials are checked, so concurrent requests cannot slip past the limit,
and a successful login (or token request) clears the count again. Two counts are kept, both keyed on the
normalised email address that was submitted, whether or not a user with that address exists
(so that the 429 answer does not tell which addresses have an account):

- per email address *and* client address (``FLEXMEASURES_AUTHENTICATION_FAILURE_LIMIT``).
  Someone guessing from one address is stopped there, while the account's owner, and scripts fetching tokens
  from other addresses, can still log in.
- per email address only, as a much higher ceiling (``FLEXMEASURES_AUTHENTICATION_FAILURE_CEILING``),
  against guessing from many addresses at once.

Once a count is used up, further attempts are refused with 429 until the window ends, whether the password
is right or not, so the answer does not tell whether it was right.

The client address is ``request.remote_addr``. Behind a reverse proxy, that is the proxy's address
unless ``FLEXMEASURES_TRUSTED_PROXIES`` is set; until then, all clients share one count per email address.

Password recovery requests (the "forgot password" form) are counted per email address,
whether or not a user with that address exists (``FLEXMEASURES_PASSWORD_RECOVERY_LIMIT``),
so the form cannot be used to flood someone's inbox.

The counts live in the rate limiter's storage (see flexmeasures.api.common.rate_limiting).
"""

from __future__ import annotations

from flask import (
    Flask,
    current_app,
    has_request_context,
    jsonify,
    make_response,
    request,
    session,
)
from limits import parse
from sqlalchemy import select

from flexmeasures.data import db

FAILURE_SCOPE = "authentication-failures"
RECOVERY_SCOPE = "password-recovery"

# Endpoints at which a user's credentials are checked, and the endpoint at which recovery is requested
CREDENTIAL_ENDPOINTS = (
    "security.login",
    "security.two_factor_token_validation",
    "flexmeasures_api.request_auth_token",
)
TOKEN_ENDPOINT = "flexmeasures_api.request_auth_token"
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


def _normalise_email(email) -> str | None:
    if not isinstance(email, str) or not email.strip():
        return None
    return email.strip().lower()


def _client_address() -> str:
    return request.remote_addr or "unknown"


def _client_key(email: str) -> str:
    return f"email:{email}|client:{_client_address()}"


def _email_key(email: str) -> str:
    return f"email:{email}"


def _failure_limit():
    return parse(current_app.config["FLEXMEASURES_AUTHENTICATION_FAILURE_LIMIT"])


def _failure_ceiling():
    return parse(current_app.config["FLEXMEASURES_AUTHENTICATION_FAILURE_CEILING"])


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
    return _normalise_email(email)


def _email_of_attempt() -> str | None:
    """Which email address the current request tries to authenticate as, if we can tell."""
    from flexmeasures.data.models.user import User

    if request.endpoint == "security.two_factor_token_validation":
        fs_uniquifier = session.get("tf_user_id")
        if not fs_uniquifier:
            return None
        return _normalise_email(
            db.session.execute(
                select(User.email).filter_by(fs_uniquifier=fs_uniquifier)
            ).scalar_one_or_none()
        )
    return _submitted_email()


def _too_many_attempts_response(message: str):
    if request.is_json or request.path.startswith("/api/"):
        response = jsonify({"status": "TOO_MANY_REQUESTS", "message": message})
    else:
        response = make_response(message)
        response.mimetype = "text/plain"
    response.status_code = 429
    return response


def refuse_attempts_beyond_limit():
    """Count each authentication attempt before the credentials are checked, and refuse it once the count is used up.

    Also counts password recovery requests.
    """
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
        email = _email_of_attempt()
        if email is None:
            return None  # the form or endpoint will say what is missing
        # Count this attempt now; a successful one is cleared again (see clear_failed_authentications)
        if not strategy.hit(
            _failure_limit(), *_identifiers(FAILURE_SCOPE, _client_key(email))
        ) or not strategy.hit(
            _failure_ceiling(), *_identifiers(FAILURE_SCOPE, _email_key(email))
        ):
            current_app.logger.warning(
                f"Refused an authentication attempt: too many failed attempts for this email address recently ({request.endpoint})."
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


def _clear(email: str | None):
    strategy = _strategy()
    if strategy is None or email is None or not has_request_context():
        return
    try:
        strategy.clear(
            _failure_limit(), *_identifiers(FAILURE_SCOPE, _client_key(email))
        )
        strategy.clear(
            _failure_ceiling(), *_identifiers(FAILURE_SCOPE, _email_key(email))
        )
    except Exception as exc:
        current_app.logger.warning(
            f"Could not clear the failed authentication attempts: {exc}"
        )


def clear_failed_authentications(sender, user=None, **kwargs):
    """Start the counts for a user's email address afresh once they logged in (connected to Flask-Login's user_logged_in signal)."""
    if user is not None:
        _clear(_normalise_email(user.email))


def clear_after_issuing_a_token(response):
    """Start the counts afresh once a token was issued (the token endpoint does not log the user in)."""
    if (
        request.method == "POST"
        and request.endpoint == TOKEN_ENDPOINT
        and response.status_code == 200
    ):
        _clear(_submitted_email())
    return response


def register_at(app: Flask):
    from flask_login import user_logged_in

    app.before_request(refuse_attempts_beyond_limit)
    app.after_request(clear_after_issuing_a_token)
    user_logged_in.connect(clear_failed_authentications, app)
