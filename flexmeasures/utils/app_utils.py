"""
Utils for serving the FlexMeasures app
"""

from __future__ import annotations

import click
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from flask import Flask, current_app, redirect
from flask.cli import FlaskGroup, with_appcontext
from flask_security import current_user
from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.rq import RqIntegration
from sentry_sdk.types import Event, Hint
from werkzeug.exceptions import NotFound

from flexmeasures import __version__ as fm_version
from flexmeasures.app import create as create_app
from flexmeasures.utils.sentry_utils import SENTRY_DEDUPLICATION_KEY_ATTRIBUTE

_SENTRY_REDIS_TIMEOUT_SECONDS = 1


def provision_default_template_assets_on_startup(app: Flask) -> None:
    """Provision starter template assets when startup settings and schema allow it."""
    if (
        not app.config.get("FLEXMEASURES_CREATE_TEMPLATE_ASSETS_ON_STARTUP", False)
        or app.testing
        or app.config.get("FLEXMEASURES_ENV") == "documentation"
    ):
        return

    if not getattr(app, "database_schema_is_migrated_to_head", True):
        app.logger.info(
            "Skipping startup template provisioning because the database schema is not at the Alembic head revision yet."
        )
        return

    from sqlalchemy.exc import OperationalError, ProgrammingError

    from flexmeasures.data import db
    from flexmeasures.data.scripts.data_gen import provision_default_template_assets

    try:
        with app.app_context():
            provision_default_template_assets(db)
    except (OperationalError, ProgrammingError) as exc:
        app.logger.warning(
            f"Skipping startup template provisioning due to an error: {exc}"
        )


@click.group(cls=FlaskGroup, create_app=create_app)
@with_appcontext
def flexmeasures_cli():
    """
    Management scripts for the FlexMeasures platform.
    """
    # We use @app_context above, so things from the app setup are initialised
    # only once! This is crucial for Sentry, for example.
    pass


# For the Sentry integration, a crucial task is to filter out noise before it reaches Sentry.
# Limiting what gets sent to Sentry (by 95%) keeps your costs to what you are interested in.
# We want to filter out 404s (also those who in addition use untrusted-host request headers),
# which are common probes in the wild.
# Note: errors may reach Sentry twice - as raised Exception plus if FlexMeasures logs the error (e.g. during handling it)
#       With verbose=False, Sentry might only see the  logging event, not an Exception, as it is only visible in the LogRecord message rather than in hint["exc_info"].


def _sentry_filter_notfound(event, hint):
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
        deduplication_key = getattr(
            hint.get("log_record"), SENTRY_DEDUPLICATION_KEY_ATTRIBUTE, None
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
        return event if is_first_report else None

    return deduplicate


def _make_sentry_daily_rate_limiter(
    app: Flask, daily_rate_limit: int, redis_connection: Redis
) -> Callable[[Event, Hint], Event | None]:
    """Build a fail-open Sentry event filter backed by a daily Redis counter."""
    redis_warning_logged = False

    def rate_limit(event: Event, hint: Hint) -> Event | None:
        nonlocal redis_warning_logged
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


def init_sentry(app: Flask):
    """
    Configure Sentry.
    We need the app to read the Sentry DSN from configuration, and also
    to send some additional meta information.
    """
    sentry_dsn = app.config.get("SENTRY_DSN")
    if not sentry_dsn:
        app.logger.info(
            "[FLEXMEASURES] No SENTRY_DSN setting found, so initialising Sentry cannot happen ..."
        )
        return
    app.logger.info("[FLEXMEASURES] Initialising Sentry ...")

    # The filters run in order, so events dropped by an earlier filter do not count towards the daily rate limit.
    filters = []
    if app.config.get("FLEXMEASURES_DO_NOT_SEND_NOTFOUND_TO_SENTRY"):
        filters.append(_sentry_filter_notfound)

    redis_connection = _make_sentry_redis_connection(app)
    filters.append(_make_sentry_daily_deduplicator(app, redis_connection))

    daily_rate_limit = app.config.get("FLEXMEASURES_SENTRY_DAILY_RATE_LIMIT")
    if daily_rate_limit is not None:
        if (
            isinstance(daily_rate_limit, bool)
            or not isinstance(daily_rate_limit, int)
            or daily_rate_limit <= 0
        ):
            app.logger.warning(
                "FLEXMEASURES_SENTRY_DAILY_RATE_LIMIT must be a positive integer "
                "or None. Sentry events will be sent without rate limiting."
            )
        else:
            filters.append(
                _make_sentry_daily_rate_limiter(app, daily_rate_limit, redis_connection)
            )

    def before_send(event, hint):
        for event_filter in filters:
            event = event_filter(event, hint)
            if event is None:
                break
        return event

    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[FlaskIntegration(), RqIntegration()],
        debug=app.debug,
        release=f"flexmeasures@{fm_version}",
        send_default_pii=True,  # user data (current user id, email address, username) is attached to the event.
        environment=app.config.get("FLEXMEASURES_ENV"),
        before_send=before_send if filters else None,
        **app.config["FLEXMEASURES_SENTRY_CONFIG"],
    )
    sentry_sdk.set_tag("mode", app.config.get("FLEXMEASURES_MODE"))
    sentry_sdk.set_tag("platform-name", app.config.get("FLEXMEASURES_PLATFORM_NAME"))


def root_dispatcher():
    """
    Re-routes to root views fitting for the current user,
    depending on the FLEXMEASURES_ROOT_VIEW setting.
    """
    default_root_view = "/dashboard"
    root_view = default_root_view
    configs = current_app.config.get("FLEXMEASURES_ROOT_VIEW", [])
    root_view = find_first_applicable_config_entry(configs, "FLEXMEASURES_ROOT_VIEW")
    if root_view in ("", "/", None):
        root_view = default_root_view
    if not root_view.startswith("/"):
        root_view = f"/{root_view}"
    current_app.logger.info(f"Redirecting root view to {root_view} ...")
    return redirect(root_view)


def find_first_applicable_config_entry(
    configs: list, setting_name: str, app: Flask | None = None
) -> str | None:
    if app is None:
        app = current_app
    if isinstance(configs, str):
        configs = [configs]  # ignore: type
    for config in configs:
        entry = parse_config_entry_by_account_roles(config, setting_name, app)
        if entry is not None:
            return entry
    return None


def parse_config_entry_by_account_roles(
    config: str | tuple[str, list[str]],
    setting_name: str,
    app: Flask | None = None,
) -> str | None:
    """
    Parse a config entry (which can be a string, e.g. "dashboard" or a tuple, e.g. ("dashboard", ["MDC"])).
    In the latter case, return the first item (a string) only if the current user's account roles match with the
    list of roles in the second item. Otherwise, return None.
    """
    if app is None:
        app = current_app
    if isinstance(config, str):
        return config
    elif isinstance(config, tuple) and len(config) == 2:
        entry, account_role_names = config
        if not isinstance(entry, str):
            app.logger.warning(
                f"View name setting '{entry}' in {setting_name} is not a string. Ignoring ..."
            )
            return None
        if not isinstance(account_role_names, list):
            app.logger.warning(
                f"Role names setting '{account_role_names}' in {setting_name} is not a list. Ignoring ..."
            )
            return None
        if not hasattr(current_user, "account"):
            # e.g. AnonymousUser
            return None
        for account_role_name in account_role_names:
            if account_role_name in [
                role.name for role in current_user.account.account_roles
            ]:
                return entry
    else:
        app.logger.warning(
            f"Setting '{config}' in {setting_name} is neither a string nor two-part tuple. Ignoring ..."
        )
    return None
