"""
Rate limiting for the FlexMeasures API.

Two limits apply:

- a generous default limit on every endpoint under ``/api/``, and
- a stricter limit on the endpoints that trigger expensive computation (scheduling and forecasting).

Both are configurable (see ``FLEXMEASURES_API_DEFAULT_RATE_LIMIT`` and ``FLEXMEASURES_API_TRIGGER_RATE_LIMIT``),
and both can be overridden per account, by setting e.g.
``account.attributes["rate_limits"]["trigger"] = "50 per hour"``.
The special value "unlimited" exempts an account from a limit.

Note that the limiter runs before authentication, so unauthenticated callers are counted by IP address.
"""

from __future__ import annotations

from flask import Flask, current_app, jsonify, request
from flask_limiter import Limiter, RequestLimit
from flask_limiter.util import get_remote_address
from flask_login import current_user

from flexmeasures.api.common.responses import too_many_requests

# Endpoints under /api/ which the default limit should not apply to
EXEMPT_PATH_PREFIXES = ("/api/v3_0/health",)


def _account_rate_limit(limit_name: str) -> str | None:
    """Look up an account's override for the given limit, if any."""
    if not current_user.is_authenticated or current_user.account is None:
        return None
    rate_limits = (current_user.account.attributes or {}).get("rate_limits", {})
    return rate_limits.get(limit_name)


def _is_unlimited(limit_name: str) -> bool:
    """Whether the account is exempt from the given limit."""
    return _account_rate_limit(limit_name) == "unlimited"


def default_key_func() -> str:
    """Count requests against the user, or against the IP address if unauthenticated."""
    if current_user.is_authenticated:
        return f"user:{current_user.id}"
    return get_remote_address()


def trigger_key_func() -> str:
    """Count triggers against whatever the host configured.

    The request path contains both the resource type and its ID,
    so it distinguishes assets from sensors without us having to parse view args.
    """
    if not current_user.is_authenticated:
        return get_remote_address()
    key = current_app.config["FLEXMEASURES_API_RATE_LIMIT_KEY"]
    if key == "user":
        return f"user:{current_user.id}"
    if key == "account":
        return f"account:{current_user.account_id}"
    if key == "account+asset":
        return f"account:{current_user.account_id}|{request.path}"
    raise ValueError(
        f"Unknown FLEXMEASURES_API_RATE_LIMIT_KEY '{key}'. Use 'account+asset', 'account' or 'user'."
    )


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
