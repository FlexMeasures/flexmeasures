"""
Utils for serving the FlexMeasures app
"""

from __future__ import annotations

import click
from flask import Flask, current_app, redirect
from flask.cli import FlaskGroup, with_appcontext
from flask_security import current_user
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.rq import RqIntegration
from werkzeug.exceptions import NotFound

from flexmeasures import __version__ as fm_version
from flexmeasures.app import create as create_app


@click.group(cls=FlaskGroup, create_app=create_app)
@with_appcontext
def flexmeasures_cli():
    """
    Management scripts for the FlexMeasures platform.
    """
    # We use @app_context above, so things from the app setup are initialised
    # only once! This is crucial for Sentry, for example.
    pass


def _sentry_filter_notfound(event, hint):
    """Filter out 404 Not Found errors to avoid inflating Sentry error budgets."""
    if "exc_info" in hint:
        exc_type, exc_value, _tb = hint["exc_info"]
        if isinstance(exc_value, NotFound):
            return None
    # FlexMeasures logs handled 404s with verbose=False to keep automated
    # scans for hackable URLs from overwhelming log files. Sentry receives
    # those as logging events, so the NotFound exception is only visible in
    # the LogRecord message rather than in hint["exc_info"].
    log_record = hint.get("log_record")
    if log_record is not None:
        message = log_record.getMessage()
        if message.startswith("NotFound - URL was: "):
            return None
    return event


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

    before_send = (
        _sentry_filter_notfound
        if app.config.get("FLEXMEASURES_DO_NOT_SEND_NOTFOUND_TO_SENTRY")
        else None
    )

    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[FlaskIntegration(), RqIntegration()],
        debug=app.debug,
        release=f"flexmeasures@{fm_version}",
        send_default_pii=True,  # user data (current user id, email address, username) is attached to the event.
        environment=app.config.get("FLEXMEASURES_ENV"),
        before_send=before_send,
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
