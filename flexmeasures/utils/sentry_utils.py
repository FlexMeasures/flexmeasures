"""
Contract between code that logs errors and the Sentry event filters serving them.
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from flask import Flask
from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry
from sentry_sdk.types import Event, Hint
from werkzeug.exceptions import NotFound

_SENTRY_REDIS_TIMEOUT_SECONDS = 1
_SENTRY_DEDUPLICATION_CONFIRMED_ATTRIBUTE = "fm_sentry_deduplication_confirmed"

SENTRY_DEDUPLICATION_KEY_ATTRIBUTE = "fm_sentry_deduplication_key"
"""Log record attribute asking Sentry to report the record once a UTC calendar day.

Set it through the `extra` argument of a logging call to say that repeated reports of the same condition are not worth their own Sentry event.
Records carrying the same key within a calendar day are reported once; records with a different key, or without the attribute, are reported as usual.
Keep the key stable for one condition, and let it cover the values that make one occurrence worth reporting separately from another.
"""


# For the Sentry integration, a crucial task is to filter out noise before it reaches Sentry.
# Limiting what gets sent to Sentry (by 95%) keeps your costs to what you are interested in.
# We want to filter out 404s (also those who in addition use untrusted-host request headers),
# which are common probes in the wild.
# Note: errors may reach Sentry twice - as raised Exception plus if FlexMeasures logs the error (e.g. during handling it)
#       With verbose=False, Sentry might only see the logging event, not an Exception, as it is only visible in the LogRecord message rather than in hint["exc_info"].


def _sentry_filter_notfound(event: Event, hint: Hint) -> Event | None:
    """Filter out noisy handled web errors to avoid inflating Sentry error budgets."""
    if "exc_info" in hint:
        _exc_type, exc_value, _tb = hint["exc_info"]
        if isinstance(exc_value, NotFound):
            return None
    # FlexMeasures logs handled 404s with verbose=False to keep automated
    # scans for hackable URLs from overwhelming log files. Sentry receives
    # those as logging events, so the NotFound exception is only visible in
    # the LogRecord message rather than in hint["exc_info"].
    # We also filter out handled SecurityErrors that are logged when untrusted-host
    # request headers are used.
    log_record = hint.get("log_record")
    if log_record is not None:
        message = log_record.getMessage()
        if message.startswith("NotFound - URL was: "):
            return None
        if (
            message.startswith("SecurityError - URL was: ")
            and " - \"Host '" in message
            and message.endswith("' is not trusted.\"")
        ):
            return None
    return event


def _make_sentry_redis_connection(app: Flask) -> Redis:
    """Build the short-timeout Redis connection used for Sentry event filtering."""
    return Redis(
        app.config["FLEXMEASURES_REDIS_URL"],
        port=app.config["FLEXMEASURES_REDIS_PORT"],
        db=app.config["FLEXMEASURES_REDIS_DB_NR"],
        password=app.config["FLEXMEASURES_REDIS_PASSWORD"],
        socket_connect_timeout=_SENTRY_REDIS_TIMEOUT_SECONDS,
        socket_timeout=_SENTRY_REDIS_TIMEOUT_SECONDS,
        retry=Retry(NoBackoff(), 0),
    )


def _make_sentry_daily_deduplicator(
    app: Flask, redis_connection: Redis
) -> Callable[[Event, Hint], Event | None]:
    """Build a fail-open Sentry event filter honouring the deduplication key of a log record.

    Conditions that every process reports while starting up would otherwise spend a host's whole Sentry allowance,
    because each of the CLI commands a host runs is a fresh start of FlexMeasures.
    Such a log record names itself through SENTRY_DEDUPLICATION_KEY_ATTRIBUTE, and is then reported once per UTC calendar day per key.
    The record is still logged in full every time, so the condition stays visible in the host's own logs.
    """
    redis_warning_logged = False

    def deduplicate(event: Event, hint: Hint) -> Event | None:
        nonlocal redis_warning_logged
        log_record = hint.get("log_record")
        deduplication_key = getattr(
            log_record, SENTRY_DEDUPLICATION_KEY_ATTRIBUTE, None
        )
        if deduplication_key is None:
            return event
        now = datetime.now(timezone.utc)
        marker_key = f"flexmeasures:sentry-deduplication:{now.date().isoformat()}:{deduplication_key}"
        expires_at = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            days=1
        )
        try:
            is_first_report = redis_connection.set(
                marker_key, 1, exat=int(expires_at.timestamp()), nx=True
            )
        except RedisError as exc:
            if not redis_warning_logged:
                redis_warning_logged = True
                app.logger.warning(
                    "Unable to deduplicate Sentry events because Redis is unavailable. "
                    "Events that would be reported once a day will be reported every time: %s",
                    exc,
                )
            return event
        if not is_first_report:
            return None
        setattr(log_record, _SENTRY_DEDUPLICATION_CONFIRMED_ATTRIBUTE, True)
        return event

    return deduplicate


def _make_sentry_daily_rate_limiter(
    app: Flask, daily_rate_limit: int, redis_connection: Redis
) -> Callable[[Event, Hint], Event | None]:
    """Build a fail-open Sentry event filter backed by a daily Redis counter."""
    redis_warning_logged = False

    def rate_limit(event: Event, hint: Hint) -> Event | None:
        nonlocal redis_warning_logged
        if getattr(
            hint.get("log_record"),
            _SENTRY_DEDUPLICATION_CONFIRMED_ATTRIBUTE,
            False,
        ):
            return event
        now = datetime.now(timezone.utc)
        counter_key = f"flexmeasures:sentry-events:{now.date().isoformat()}"
        try:
            expires_at = now.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
            pipeline = redis_connection.pipeline()
            pipeline.incr(counter_key)
            pipeline.expireat(counter_key, int(expires_at.timestamp()))
            event_count, _ = pipeline.execute()
        except RedisError as exc:
            if not redis_warning_logged:
                redis_warning_logged = True
                app.logger.warning(
                    "Unable to apply the Sentry daily rate limit because Redis is "
                    "unavailable. Sentry events will be sent without rate limiting: %s",
                    exc,
                )
            return event
        return event if event_count <= daily_rate_limit else None

    return rate_limit
