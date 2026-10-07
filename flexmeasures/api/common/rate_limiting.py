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

Neither limit applies on a play server (``FLEXMEASURES_MODE`` is "play"), which is the mode for running
simulations ― precisely the tight trigger loop the trigger limit exists to stop. Note that this is about
the play mode, not about running in development: a development server rate-limits like any other, so that
what you see there is what you get in production.
"""

from __future__ import annotations

from typing import Iterable

from flask import Flask, Response, current_app, jsonify, request
from flask_limiter import Limiter, RequestLimit
from flask_limiter.util import get_remote_address
from flask_login import current_user
from limits import parse_many

from flexmeasures.api.common.responses import too_many_requests
from flexmeasures.data.models.user import Account, Plan
from flexmeasures.utils.validation_utils import UNLIMITED_RATE_LIMIT

# Endpoints under /api/ which the default limit should not apply to
EXEMPT_PATH_PREFIXES = ("/api/v3_0/health",)

# Qualified names of the views which limit_triggers() decorated, so that the OpenAPI specs
# can tell which endpoints hit the stricter trigger limit on top of the default one.
TRIGGER_LIMITED_VIEWS: set[str] = set()

# The buckets which each limit counts in: all trigger endpoints share one,
# and the default limit is an application limit, which Flask-Limiter counts in the "global" scope.
TRIGGER_SCOPE = "triggers"
DEFAULT_SCOPE = "global"

# The limits there are, and the config settings which set them server-wide
RATE_LIMIT_SETTINGS = {
    "default": "FLEXMEASURES_API_DEFAULT_RATE_LIMIT",
    "trigger": "FLEXMEASURES_API_TRIGGER_RATE_LIMIT",
}


def _plan():
    """The plan of the current user's account, if any."""
    if not current_user.is_authenticated or current_user.account is None:
        return None
    return current_user.account.plan


def _plan_rate_limit(plan: Plan | None, limit_name: str) -> str | None:
    """Look up a plan's override for the given limit, if any."""
    if plan is None:
        return None
    if limit_name == "default":
        return plan.default_rate_limit
    if limit_name == "trigger":
        return plan.trigger_rate_limit
    return None


def _account_rate_limit(limit_name: str) -> str | None:
    """Look up the current user's account's plan-level override for the given limit, if any."""
    return _plan_rate_limit(_plan(), limit_name)


def _is_unlimited(limit_name: str) -> bool:
    """Whether the account is exempt from the given limit."""
    return _account_rate_limit(limit_name) == UNLIMITED_RATE_LIMIT


def _is_play_mode() -> bool:
    """Whether this server is for running simulations, which trigger computation in tight loops.

    Deliberately keyed on the play mode rather than on the development environment: a dev server
    should rate-limit like production does, or the limits only ever surface once they are live.
    """
    return current_app.config.get("FLEXMEASURES_MODE") == "play"


def _user_key(user_id: int) -> str:
    return f"user:{user_id}"


def _account_key(account_id: int) -> str:
    return f"account:{account_id}"


def default_key_func() -> str:
    """Count requests against the user, or against the IP address if unauthenticated."""
    if current_user.is_authenticated:
        return _user_key(current_user.id)
    return get_remote_address()


def trigger_key_func() -> str:
    """Count triggers against the account, or against the IP address if unauthenticated.

    The account is what a plan belongs to, so its trigger budget is shared by all of its users and assets.
    """
    if not current_user.is_authenticated:
        return get_remote_address()
    return _account_key(current_user.account_id)


def warn_about_deprecated_settings(app: Flask):
    """Tell hosts who still choose what triggers are counted against that this choice is gone."""
    key = app.config.get("FLEXMEASURES_API_RATE_LIMIT_KEY", "account")
    if key != "account":
        app.logger.warning(
            f"FLEXMEASURES_API_RATE_LIMIT_KEY is deprecated and ignored (it is set to '{key}'). "
            "Triggers are now always counted per account. "
            "To give accounts more room, raise their plan's trigger rate limit, or FLEXMEASURES_API_TRIGGER_RATE_LIMIT."
        )


def _limit(limit_name: str, config_key: str) -> str:
    """The plan's limit if it sets one, else the server-wide config setting.

    Never returns the "unlimited" sentinel: that is not a limit the parser understands,
    but an exemption, which the exempt_when callables grant. What we return in that case
    is irrelevant, as long as it parses.
    """
    return _limit_on_plan(_plan(), limit_name, config_key)


def _limit_on_plan(plan: Plan | None, limit_name: str, config_key: str) -> str:
    """The plan's limit if it sets one, else the server-wide config setting (see _limit)."""
    plan_limit = _plan_rate_limit(plan, limit_name)
    if plan_limit is None or plan_limit == UNLIMITED_RATE_LIMIT:
        return current_app.config[config_key]
    return plan_limit


def default_limit() -> str:
    return _limit("default", "FLEXMEASURES_API_DEFAULT_RATE_LIMIT")


def trigger_limit() -> str:
    return _limit("trigger", "FLEXMEASURES_API_TRIGGER_RATE_LIMIT")


def _exempt_from_default_limit() -> bool:
    """The default limit only applies to the API, and not to endpoints we exempt explicitly."""
    if not request.path.startswith("/api/"):
        return True
    if request.path.startswith(EXEMPT_PATH_PREFIXES):
        return True
    if _is_play_mode():
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
    limit = limiter.shared_limit(
        trigger_limit,
        # All trigger endpoints share one budget. Without this, each of them would get its own,
        # so a client could ask for twice as many schedules by alternating between the asset
        # endpoint and the (deprecated) sensor endpoint.
        scope=TRIGGER_SCOPE,
        key_func=trigger_key_func,
        exempt_when=lambda: _is_play_mode() or _is_unlimited("trigger"),
        deduct_when=_trigger_set_work_in_motion,
    )

    def decorator(view):
        TRIGGER_LIMITED_VIEWS.add(view.__qualname__)
        return limit(view)

    return decorator


def _counter_keys(account: Account, limit_name: str) -> list[str]:
    """What an account's requests are counted against, for the given limit.

    Keep this in line with the key functions above: triggers are counted against the account,
    while the default limit is counted against each of the account's users.
    """
    if limit_name == "trigger":
        return [_account_key(account.id)]
    return [_user_key(user.id) for user in account.users]


def reset_rate_limits(
    account: Account, limit_names: Iterable[str] = tuple(RATE_LIMIT_SETTINGS)
) -> list[str]:
    """Clear an account's rate-limit counters, so that its requests are accepted again straight away.

    We clear the counters of the limits in effect for the account (its plan's, or the server-wide ones).
    The limit's amount is part of a counter's key, so counters left over from a limit that no longer applies are not counted against anymore, and simply expire.
    A limit the account is exempt from ("unlimited") has nothing to reset, and is skipped.

    Returns the names of the limits that were reset.
    """
    scopes = {"default": DEFAULT_SCOPE, "trigger": TRIGGER_SCOPE}
    key_prefix = [limiter._key_prefix] if limiter._key_prefix else []
    reset = []
    for limit_name in limit_names:
        if _plan_rate_limit(account.plan, limit_name) == UNLIMITED_RATE_LIMIT:
            continue
        limit_string = _limit_on_plan(
            account.plan, limit_name, RATE_LIMIT_SETTINGS[limit_name]
        )
        for item in parse_many(limit_string):
            for key in _counter_keys(account, limit_name):
                limiter.limiter.clear(item, *key_prefix, key, scopes[limit_name])
        reset.append(limit_name)
    return reset


def rate_limit_exceeded_handler(error):
    """Respond to a hit rate limit like we respond to other API errors.

    The Retry-After and X-RateLimit-* headers are added by the limiter itself, after this request.
    """
    limit: RequestLimit | None = limiter.current_limit
    message = "You hit a rate limit."
    if limit is not None:
        # Not "this endpoint": the default limit spans the whole API,
        # and the trigger limit is shared by all trigger endpoints.
        message += f" The limit you hit allows {limit.limit}."
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

    warn_about_deprecated_settings(app)
    limiter.init_app(app)
    app.register_error_handler(429, rate_limit_exceeded_handler)
