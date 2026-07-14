"""
Rate limiting for the FlexMeasures API.

Two limits apply:

- a generous default limit on every endpoint under ``/api/``, and
- a stricter limit on the endpoints that trigger expensive computation (scheduling and forecasting).

Both are configurable (see ``FLEXMEASURES_API_DEFAULT_RATE_LIMIT`` and ``FLEXMEASURES_API_TRIGGER_RATE_LIMIT``),
and both can be overridden per account, by assigning the account a ``Plan`` with
``default_rate_limit`` and/or ``trigger_rate_limit`` set (see ``flexmeasures.data.models.user.Plan``).
The special value "unlimited" exempts an account from a limit.

The two limits count differently. The default limit counts every request, including those we refuse
(so that a client hammering us with bad credentials is bounded, too). The trigger limit only counts
triggers we accepted, because it exists to protect the expensive computation which those set in motion:
a client whose payload we rejected did not cost us a schedule, and should not pay for one.

Note that the limiter runs before authentication, so unauthenticated callers are counted by IP address.
"""

from __future__ import annotations

from flask import Flask, Response, current_app, jsonify, request
from flask_limiter import Limiter, RequestLimit
from flask_limiter.util import get_remote_address
from flask_login import current_user

from flexmeasures.api.common.responses import too_many_requests
from flexmeasures.data import db
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import RateLimitKey
from flexmeasures.utils.validation_utils import UNLIMITED_RATE_LIMIT

# Endpoints under /api/ which the default limit should not apply to
EXEMPT_PATH_PREFIXES = ("/api/v3_0/health",)

_VALID_RATE_LIMIT_KEYS = {key.value for key in RateLimitKey}


def _plan():
    """The plan of the current user's account, if any."""
    if not current_user.is_authenticated or current_user.account is None:
        return None
    return current_user.account.plan


def _account_rate_limit(limit_name: str) -> str | None:
    """Look up an account's plan-level override for the given limit, if any."""
    plan = _plan()
    if plan is None:
        return None
    if limit_name == "default":
        return plan.default_rate_limit
    if limit_name == "trigger":
        return plan.trigger_rate_limit
    return None


def _is_unlimited(limit_name: str) -> bool:
    """Whether the account is exempt from the given limit."""
    return _account_rate_limit(limit_name) == UNLIMITED_RATE_LIMIT


def default_key_func() -> str:
    """Count requests against the user, or against the IP address if unauthenticated."""
    if current_user.is_authenticated:
        return f"user:{current_user.id}"
    return get_remote_address()


def _rate_limit_key_value() -> str:
    """Determine what to count triggers against: the account's plan, or the server config.

    Falls back to the server config (and ultimately to a hardcoded default) rather than raising,
    so that a bad value never turns into a 500 on every request for an account.
    """
    plan = _plan()
    if plan is not None and plan.rate_limit_key is not None:
        return plan.rate_limit_key.value
    key = current_app.config["FLEXMEASURES_API_RATE_LIMIT_KEY"]
    if key not in _VALID_RATE_LIMIT_KEYS:
        current_app.logger.error(
            f"Unknown FLEXMEASURES_API_RATE_LIMIT_KEY '{key}'. "
            f"Use one of {sorted(_VALID_RATE_LIMIT_KEYS)}. Falling back to '{RateLimitKey.ACCOUNT.value}'."
        )
        return RateLimitKey.ACCOUNT.value
    return key


def _asset_id_of_trigger() -> int | None:
    """Which asset a trigger request is about.

    The asset endpoint names the asset in its path, while the (deprecated) sensor endpoints name a sensor,
    so we resolve that sensor's asset. That way, both ways of triggering the same asset share one budget.
    Returns None if we cannot tell, which the caller reads as "count this against the account as a whole".
    """
    resource_id = (request.view_args or {}).get("id")
    try:
        resource_id = int(resource_id)
    except (TypeError, ValueError):
        return None  # the view is about to reject this request anyway
    if "/assets/" in request.path:
        return resource_id
    sensor = db.session.get(Sensor, resource_id)
    return sensor.generic_asset_id if sensor is not None else None


def trigger_key_func() -> str:
    """Count triggers against whatever the host (or the account's plan) configured."""
    if not current_user.is_authenticated:
        return get_remote_address()
    key = _rate_limit_key_value()
    if key == RateLimitKey.USER.value:
        return f"user:{current_user.id}"
    account_key = f"account:{current_user.account_id}"
    if key == RateLimitKey.ACCOUNT.value:
        return account_key
    asset_id = _asset_id_of_trigger()  # "account+asset"
    if asset_id is None:
        return account_key
    return f"{account_key}|asset:{asset_id}"


def default_limit() -> str:
    return (
        _account_rate_limit("default")
        or current_app.config["FLEXMEASURES_API_DEFAULT_RATE_LIMIT"]
    )


def trigger_limit() -> str:
    return (
        _account_rate_limit("trigger")
        or current_app.config["FLEXMEASURES_API_TRIGGER_RATE_LIMIT"]
    )


def _exempt_from_default_limit() -> bool:
    """The default limit only applies to the API, and not to endpoints we exempt explicitly."""
    if not request.path.startswith("/api/"):
        return True
    if request.path.startswith(EXEMPT_PATH_PREFIXES):
        return True
    return _is_unlimited("default")


limiter = Limiter(
    key_func=default_key_func,
    # An application limit is one budget for the whole API, rather than one budget per endpoint,
    # which is what "how often a client may call the API" should mean.
    application_limits=[default_limit],
    application_limits_exempt_when=_exempt_from_default_limit,
    headers_enabled=True,  # sets Retry-After and X-RateLimit-* headers
)


def _trigger_set_work_in_motion(response: Response) -> bool:
    """Whether a trigger request got to the expensive part, and should therefore be counted.

    A request we refused (bad credentials, no permission, invalid payload) cost us no computation,
    so it does not spend the account's trigger budget. Such requests are still counted by the default
    limit, which applies to every API endpoint.
    """
    return response.status_code < 400


def limit_triggers():
    """Decorator for endpoints which trigger expensive computation, like scheduling."""
    return limiter.shared_limit(
        trigger_limit,
        # All trigger endpoints share one budget. Without this, each of them would get its own,
        # so a client could ask for twice as many schedules by alternating between the asset
        # endpoint and the (deprecated) sensor endpoint.
        scope="triggers",
        key_func=trigger_key_func,
        exempt_when=lambda: _is_unlimited("trigger"),
        deduct_when=_trigger_set_work_in_motion,
    )


def rate_limit_exceeded_handler(error):
    """Respond to a hit rate limit like we respond to other API errors.

    The Retry-After and X-RateLimit-* headers are added by the limiter itself, after this request.
    """
    limit: RequestLimit | None = limiter.current_limit
    message = "You hit a rate limit."
    if limit is not None:
        message += f" This endpoint allows {limit.limit}."
    response_data, status_code = too_many_requests(message)
    response = jsonify(response_data)
    response.status_code = status_code
    return response


def register_at(app: Flask):
    """Set up rate limiting, storing counts in the Redis we already connected to."""
    app.config.setdefault("RATELIMIT_STORAGE_URI", "redis://")
    if app.config["RATELIMIT_STORAGE_URI"].startswith("redis://"):
        # Reuse the connection we already made, rather than opening a second one
        app.config.setdefault(
            "RATELIMIT_STORAGE_OPTIONS",
            {"connection_pool": app.redis_connection.connection_pool},
        )
    # If Redis is unreachable, let requests through rather than take the API down with it.
    app.config.setdefault("RATELIMIT_SWALLOW_ERRORS", True)
    app.config.setdefault("RATELIMIT_IN_MEMORY_FALLBACK_ENABLED", True)

    limiter.init_app(app)
    app.register_error_handler(429, rate_limit_exceeded_handler)
