from typing import Union, Tuple, List, Optional
import os
import sys
import importlib.util
from importlib.abc import Loader

import click
from flask import Blueprint, Flask, current_app, redirect
from flask.cli import FlaskGroup, with_appcontext
from flask_security import current_user
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.rq import RqIntegration
from pkg_resources import get_distribution

from flexmeasures.app import create as create_app


@click.group(cls=FlaskGroup, create_app=create_app)
@with_appcontext
def flexmeasures_cli():
    """
    Management scripts for the FlexMeasures platform.
    We use @app_context here so things from the app setup are initialised
    only once. This is crucial for Sentry, for example.
    """
    pass


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
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[FlaskIntegration(), RqIntegration()],
        debug=app.debug,
        release=f"flexmeasures@{get_distribution('flexmeasures').version}",
        send_default_pii=True,  # user data (current user id, email address, username) is attached to the event.
        environment=app.env,
        **app.config["FLEXMEASURES_SENTRY_CONFIG"],
    )
    sentry_sdk.set_tag("mode", app.config.get("FLEXMEASURES_MODE"))
    sentry_sdk.set_tag("platform-name", app.config.get("FLEXMEASURES_PLATFORM_NAME"))


def set_secret_key(app, filename="secret_key"):
    """Set the SECRET_KEY or exit.

    We first check if it is already in the config.

    Then we look for it in environment var SECRET_KEY.

    Finally, we look for `filename` in the app's instance directory.

    If nothing is found, we print instructions
    to create the secret and then exit.
    """
    secret_key = app.config.get("SECRET_KEY", None)
    if secret_key is not None:
        return
    secret_key = os.environ.get("SECRET_KEY", None)
    if secret_key is not None:
        app.config["SECRET_KEY"] = secret_key
        return
    filename = os.path.join(app.instance_path, filename)
    try:
        app.config["SECRET_KEY"] = open(filename, "rb").read()
    except IOError:
        app.logger.error(
            """
        Error:  No secret key set.

        You can add the SECRET_KEY setting to your conf file (this example works only on Unix):

        echo "SECRET_KEY=\\"`head -c 24 /dev/urandom`\\"" >> your-flexmeasures.cfg

        OR you can add an env var:

        export SECRET_KEY=xxxxxxxxxxxxxxx
        (on windows, use "set" instead of "export")

        OR you can create a secret key file (this example works only on Unix):

        mkdir -p %s
        head -c 24 /dev/urandom > %s

        You can also use Python to create a good secret:

        python -c "import secrets; print(secrets.token_urlsafe())"

        """
            % (os.path.dirname(filename), filename)
        )

        sys.exit(2)


def root_dispatcher():
    """
    Re-routes to root views fitting for the current user,
    depending on the FLEXMEASURES_ROOT_VIEW setting.
    """
    default_root_view = root_view = "/dashboard"
    configs = current_app.config.get("FLEXMEASURES_ROOT_VIEW", [])
    root_view = find_first_applicable_config_entry(configs, "FLEXMEASURES_ROOT_VIEW")
    if not root_view.startswith("/"):
        root_view = f"/{root_view}"
    if root_view in ("", "/", None):
        root_view = default_root_view
    current_app.logger.info(f"Redirecting root view to {root_view} ...")
    return redirect(root_view)


def find_first_applicable_config_entry(
    configs: list, setting_name: str, app: Optional[Flask] = None
) -> Optional[str]:
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
    config: Union[str, Tuple[str, List[str]]],
    setting_name: str,
    app: Optional[Flask] = None,
) -> Optional[str]:
    """
    Parse a config entry (which ca be a string, e.g. "dashboard" or a tuple, e.g. ("dashboard", ["MDC"])).
    In the latter case, return the first item (a string) only if the current user's account roles match with the
    list of roles in the second item. Otherwise return None.
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
        app.logger.warn(
            f"Setting '{config}' in {setting_name} is neither a string nor two-part tuple. Ignoring ..."
        )
    return None


def register_plugins(app: Flask):
    """
    Register FlexMeasures plugins as Blueprints.
    This is configured by the config setting FLEXMEASURES_PLUGIN_PATHS.

    Assumptions:
    - Your plugin folders contains an __init__.py file.
    - In that file, you define a Blueprint object (or several).

    We'll refer to the plugins with the name of your plugin folders (last part of the path).
    """
    plugin_paths = app.config.get("FLEXMEASURES_PLUGIN_PATHS", "")
    if not isinstance(plugin_paths, list):
        app.logger.warning(
            f"The value of FLEXMEASURES_PLUGIN_PATHS is not a list: {plugin_paths}. Cannot install plugins ..."
        )
        return
    app.config["LOADED_PLUGINS"] = {}
    for plugin_path in plugin_paths:
        plugin_name = plugin_path.split("/")[-1]
        if not os.path.exists(os.path.join(plugin_path, "__init__.py")):
            app.logger.warning(
                f"Plugin {plugin_name} does not contain an '__init__.py' file. Cannot load plugin {plugin_name}."
            )
            return
        app.logger.debug(f"Importing plugin {plugin_name} ...")
        spec = importlib.util.spec_from_file_location(
            plugin_name, os.path.join(plugin_path, "__init__.py")
        )
        if spec is None:
            app.logger.warning(
                f"Could not load specs for plugin {plugin_name} at {plugin_path}."
            )
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[plugin_name] = module
        assert isinstance(spec.loader, Loader)
        spec.loader.exec_module(module)

        # Look for blueprints in the plugin's main __init__ module and register them
        plugin_blueprints = [
            getattr(module, a)
            for a in dir(module)
            if isinstance(getattr(module, a), Blueprint)
        ]
        if not plugin_blueprints:
            app.logger.warning(
                f"No blueprints found for plugin {plugin_name} at {plugin_path}."
            )
            continue
        for plugin_blueprint in plugin_blueprints:
            app.register_blueprint(plugin_blueprint)

        plugin_version = getattr(plugin_blueprint, "__version__", "0.1")
        app.config["LOADED_PLUGINS"][plugin_name] = plugin_version
    app.logger.info(f"Loaded plugins: {app.config['LOADED_PLUGINS']}")
    sentry_sdk.set_context("plugins", app.config.get("LOADED_PLUGINS", {}))
