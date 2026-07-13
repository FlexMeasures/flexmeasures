"""
Rate limiting for the FlexMeasures API.

Two limits apply:

- a generous default limit on every endpoint under ``/api/``, and
- a stricter limit on the endpoints that trigger expensive computation (scheduling and forecasting).

Both are configurable (see ``FLEXMEASURES_API_DEFAULT_RATE_LIMIT`` and ``FLEXMEASURES_API_TRIGGER_RATE_LIMIT``),
and both can be overridden per account, by assigning the account a ``Plan`` with
``default_rate_limit`` and/or ``trigger_rate_limit`` set (see ``flexmeasures.data.models.user.Plan``).
The special value "unlimited" exempts an account from a limit.

Note that the limiter runs before authentication, so unauthenticated callers are counted by IP address.
"""

from __future__ import annotations

from flask import Flask, current_app, jsonify, request
from flask_limiter import Limiter, RequestLimit
from flask_limiter.util import get_remote_address
from flask_login import current_user

from flexmeasures.api.common.responses import too_many_requests
from flexmeasures.data.models.user import RateLimitKey

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
    return _account_rate_limit(limit_name) == "unlimited"


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
            f"Use one of {sorted(_VALID_RATE_LIMIT_KEYS)}. Falling back to '{RateLimitKey.ACCOUNT_PLUS_ASSET.value}'."
        )
        return RateLimitKey.ACCOUNT_PLUS_ASSET.value
    return key


def trigger_key_func() -> str:
    """Count triggers against whatever the host (or the account's plan) configured.

    The request path contains both the resource type and its ID,
    so it distinguishes assets from sensors without us having to parse view args.
    """
    if not current_user.is_authenticated:
        return get_remote_address()
    key = _rate_limit_key_value()
    if key == "user":
        return f"user:{current_user.id}"
    if key == "account":
        return f"account:{current_user.account_id}"
    return f"account:{current_user.account_id}|{request.path}"  # "account+asset"


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
    default_limits=[default_limit],
    default_limits_exempt_when=_exempt_from_default_limit,
    headers_enabled=True,  # sets Retry-After and X-RateLimit-* headers
)


def limit_triggers():
    """Decorator for endpoints which trigger expensive computation, like scheduling."""
    return limiter.limit(
        trigger_limit,
        key_func=trigger_key_func,
        exempt_when=lambda: _is_unlimited("trigger"),
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
