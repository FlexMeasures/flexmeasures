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

The default limit is counted per account, so that all users and integrations of an account share one budget (set in the account's plan).
By an integration, we mean anything which calls the API with an auth token, rather than through the UI.
A user of a consultancy account counts against the consultancy's account, also when acting on a client account's assets.
The UI is the exception: its pages call the API with the session of the user who is logged in, rather than with a token,
and those requests count against a budget per user (``FLEXMEASURES_UI_RATE_LIMIT``), which plans do not touch.
That way, an integration which uses up its account's budget does not lock the account's users out of the UI,
and browsing the UI does not spend the budget which the account's integrations need.
Note that the limiter runs before authentication, so unauthenticated callers are counted by IP address.

Each refused request is logged as a warning, saying who hit which limit, on which endpoint (and, for triggers, about which asset),
because a budget is shared by everyone it counts, so a 429 alone does not tell a host who used it up.

Neither limit applies on a play server (``FLEXMEASURES_MODE`` is "play"), which is the mode for running
simulations ― precisely the tight trigger loop the trigger limit exists to stop. Note that this is about
the play mode, not about running in development: a development server rate-limits like any other, so that
what you see there is what you get in production.
"""

from __future__ import annotations

import logging
from typing import Iterable

from flask import Flask, Response, current_app, jsonify, request
from flask_limiter import Limiter, RequestLimit
from flask_limiter.util import get_remote_address
from flask_login import current_user
from flask_security import get_request_attr
from limits import parse
from limits.storage import RedisStorage
from redis.exceptions import RedisError
from sqlalchemy import insert
from sqlalchemy.exc import SQLAlchemyError

from flexmeasures.data import db
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.api.common.responses import too_many_requests
from flexmeasures.data.models.user import Account, Plan
from flexmeasures.utils.time_utils import server_now
from flexmeasures.utils.validation_utils import UNLIMITED_RATE_LIMIT

# Endpoints under /api/ which the default limit should not apply to
EXEMPT_PATH_PREFIXES = ("/api/v3_0/health",)

# Redis Lua script, run atomically by EVAL to claim one audit marker per window.
# KEYS[1] is the breached limit's full Redis counter key (including account and limit).
# Read its TTL without changing the request count; write only to KEYS[2], our
# separate audit marker key. Only the marker's existence matters, so its value
# is the descriptive string "claimed". It expires with the counter.
# Return its remaining TTL in milliseconds if newly claimed, or 0 if there is
# no expiring counter or another request has already claimed the marker.
_TRY_CLAIM_RATE_LIMIT_AUDIT_MARKER = """
local remaining_ttl_ms = redis.call('PTTL', KEYS[1])
if remaining_ttl_ms <= 0 then return 0 end
if redis.call('SET', KEYS[2], 'claimed', 'PX', remaining_ttl_ms, 'NX') then return remaining_ttl_ms end
return 0
"""

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


def _is_ui_request() -> bool:
    """Whether the request comes from the UI, rather than from an integration.

    Integrations authenticate with a token, while the UI's pages call the API with the session cookie of the user who is logged in.
    We ask Flask-Security which of the two it used to load the user, as it accepts a token in a request header,
    in the query string and in a JSON body.
    """
    if not current_user.is_authenticated:
        return False
    return get_request_attr("fs_authn_via") == "session"
def _account_key(account_id: int) -> str:
    return f"account:{account_id}"


def default_key_func() -> str:
    """Count requests against the user's account, or against the IP address if unauthenticated.

    All users and integrations of an account share one budget, which is what the account's plan sets.
    A consultant counts against their own account, also when acting on a client account's assets,
    because it is the consultancy's integration which makes the requests.
    Requests from the UI count against the user instead, in a budget of their own (see default_limit).
    """
    if not current_user.is_authenticated:
        return get_remote_address()
    if _is_ui_request():
        return f"ui-user:{current_user.id}"
    return _account_key(current_user.account_id)


def _asset_id_of_trigger() -> int | None:
    """Which asset a trigger request is about.

    The asset endpoint names the asset in its path, while the (deprecated) sensor endpoints name a sensor,
    so we resolve that sensor's asset. That way, both ways of triggering the same asset share one budget.
    Returns None if we cannot tell, which the caller reads as "count this against the account as a whole".
    """
    raw_id = (request.view_args or {}).get("id")
    if raw_id is None:
        return None
    try:
        resource_id = int(raw_id)
    except (TypeError, ValueError):
        return None  # the view is about to reject this request anyway
    if "/assets/" in request.path:
        return resource_id
    sensor = db.session.get(Sensor, resource_id)
    return sensor.generic_asset_id if sensor is not None else None


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
    """The UI's budget per user for requests from the UI, and otherwise the account's budget."""
    if _is_ui_request():
        return current_app.config["FLEXMEASURES_UI_RATE_LIMIT"]
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
    if _is_ui_request():
        # A plan sets the budget of the account's integrations, not of the UI.
        return False
    return _is_unlimited("default")


limiter = Limiter(
    key_func=default_key_func,
    # An application limit is one budget for the whole API, rather than one budget per endpoint,
    # which is what "how often a client may call the API" should mean.
    application_limits=[default_limit],
    application_limits_exempt_when=_exempt_from_default_limit,
    headers_enabled=True,  # sets Retry-After and X-RateLimit-* headers
)


def _requester() -> str:
    """Who made the current request, for the logs: their account and user, or their IP address."""
    if not current_user.is_authenticated:
        return f"unauthenticated caller {get_remote_address()}"
    return f"account {current_user.account_id}, user {current_user.id}"


def _endpoint() -> str:
    """Which endpoint the current request is for, for the logs."""
    return f"{request.method} {request.path} ({request.endpoint})"


def _trigger_set_work_in_motion(response: Response) -> bool:
    """Whether a trigger request got to the expensive part, and should therefore be counted.

    A request we refused (bad credentials, no permission, invalid payload) cost us no computation,
    so it does not spend the account's trigger budget. Such requests are still counted by the default
    limit, which applies to every API endpoint.

    Counted triggers are logged at debug level, so that a host can see what spent a budget before it ran out.
    """
    counted = response.status_code < 400
    if counted and current_app.logger.isEnabledFor(logging.DEBUG):
        # Checking the log level first spares us the asset lookup, which may query the database
        current_app.logger.debug(
            f"Counted a trigger against the trigger rate limit: {_requester()}, asset {_asset_id_of_trigger()}, {_endpoint()}."
        )
    return counted


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
        limiter.limiter.clear(
            parse(limit_string),
            *key_prefix,
            _account_key(account.id),
            scopes[limit_name],
        )
        reset.append(limit_name)
    return reset


def _log_rate_limit_hit(error):
    """Log who hit which limit, and where.

    Limits are counted per budget (an account, say), so a 429 alone does not tell a host which integration used that budget up.
    """
    runtime_limit = getattr(error, "limit", None)
    if runtime_limit is None:
        # Not raised by the limiter, so we cannot tell which limit this was
        limit_description = "an unknown limit"
        is_trigger_limit = False
    else:
        is_trigger_limit = runtime_limit.scope == TRIGGER_SCOPE
        if is_trigger_limit:
            limit_name = "trigger"
        elif _is_ui_request():
            limit_name = "UI"
        else:
            limit_name = "default"
        limit_description = f"the {limit_name} rate limit ({runtime_limit.limit})"
    asset = f", asset {_asset_id_of_trigger()}" if is_trigger_limit else ""
    current_app.logger.warning(
        f"Refused a request for hitting {limit_description}: {_requester()}{asset}, {_endpoint()}."
    )


def _audit_rate_limit_hit(error) -> None:
    """Record the first breach of an account's API or trigger budget in its audit log."""
    runtime_limit = getattr(error, "limit", None)
    limit: RequestLimit | None = limiter.current_limit
    # Only account-level limiter breaches have a plan and a shared audit window.
    if (
        runtime_limit is None
        or runtime_limit.scope not in ("global", TRIGGER_SCOPE)
        or limit is None
        or not limit.breached
        or not current_user.is_authenticated
        or current_user.account is None
    ):
        return
    if runtime_limit.scope != TRIGGER_SCOPE and _is_ui_request():
        # The user ran out of their UI budget, which is theirs rather than the account's.
        return

    account = current_user.account
    limit_name = "trigger" if runtime_limit.scope == TRIGGER_SCOPE else "API"
    plan = account.plan
    plan_label = f"plan '{plan.name}' (ID {plan.id})" if plan else "no plan"
    plan_override = (
        (
            plan.trigger_rate_limit
            if limit_name == "trigger"
            else plan.default_rate_limit
        )
        if plan
        else None
    )
    limit_source = "plan override" if plan_override is not None else "server default"
    event_time = server_now()
    window_seconds = limit.limit.get_expiry()

    try:
        storage = limit.limiter.storage
        if (
            isinstance(storage, RedisStorage)
            and current_app.config.get("RATELIMIT_STRATEGY", "fixed-window")
            == "fixed-window"
        ):
            counter_key = storage.prefixed_key(limit.key)
            marker_key = f"{{{counter_key}}}:account-audit"
            # EVAL's 2 maps counter_key and marker_key to Lua KEYS[1] and KEYS[2].
            claimed_ttl_ms = storage.get_connection().eval(
                _TRY_CLAIM_RATE_LIMIT_AUDIT_MARKER, 2, counter_key, marker_key
            )
            # No current window to audit, or another request claimed it already.
            if claimed_ttl_ms == 0:
                return
            remaining_seconds = claimed_ttl_ms / 1000
        else:
            # Other storage backends use the stable reset time to identify this window.
            remaining_seconds = max(0, limit.window.reset_time - event_time.timestamp())
            if remaining_seconds == 0:
                return
            marker_key = f"{limit.key}:account-audit:{limit.window.reset_time}"
            if storage.incr(marker_key, expiry=remaining_seconds) != 1:
                return

        # Report when the shared budget ran out, relative to its full window.
        elapsed_seconds = min(
            window_seconds, max(0, round(window_seconds - remaining_seconds))
        )
        elapsed_percent = round(100 * elapsed_seconds / window_seconds)
        event = (
            f"{limit_name} rate limit breached for {plan_label}: {limit.limit} ({limit_source}); "
            f"{elapsed_seconds}s into {window_seconds}s window ({elapsed_percent}%)"
        )
        # Commit the audit independently without committing unrelated request state.
        with db.engine.begin() as connection:
            connection.execute(
                insert(AuditLog).values(
                    event_datetime=event_time,
                    event=event,
                    affected_account_id=account.id,
                )
            )
    except (RedisError, SQLAlchemyError):
        current_app.logger.exception(
            "Could not record a rate-limit breach in the account audit log"
        )


def rate_limit_exceeded_handler(error):
    """Respond to a hit rate limit like we respond to other API errors.

    The Retry-After and X-RateLimit-* headers are added by the limiter itself, after this request.
    """
    _log_rate_limit_hit(error)
    _audit_rate_limit_hit(error)
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
