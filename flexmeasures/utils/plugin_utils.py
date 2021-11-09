import importlib.util
import os
import sys
from importlib.abc import Loader
from typing import Dict

import sentry_sdk
from flask import Flask, Blueprint


def register_plugins(app: Flask):
    """
    Register FlexMeasures plugins as Blueprints.
    This is configured by the config setting FLEXMEASURES_PLUGINS.

    Assumptions:
    - a setting EITHER points to a plugin folder containing an __init__.py file
      OR it is the name of an installed module, which can be imported.
    - each plugin defines at least one Blueprint object. These will be registered with the Flask app,
      so their functionality (e.g. routes) becomes available.

    If you load a plugin via a file path, we'll refer to the plugin with the name of your plugin folder
    (last part of the path).
    """
    plugins = app.config.get("FLEXMEASURES_PLUGINS", [])
    if not plugins:
        # this is deprecated behaviour which we should remove in version 1.0
        app.logger.debug(
            "No plugins configured. Attempting deprecated setting FLEXMEASURES_PLUGIN_PATHS ..."
        )
        plugins = app.config.get("FLEXMEASURES_PLUGIN_PATHS", [])
    if not isinstance(plugins, list):
        app.logger.error(
            f"The value of FLEXMEASURES_PLUGINS is not a list: {plugins}. Cannot install plugins ..."
        )
        return
    app.config["LOADED_PLUGINS"] = {}
    for plugin in plugins:
        plugin_name = plugin.split("/")[-1]
        app.logger.info(f"Importing plugin {plugin_name} ...")
        module = None
        if not os.path.exists(plugin):  # assume plugin is a package
            pkg_name = os.path.split(plugin)[
                -1
            ]  # rule out attempts for relative package imports
            app.logger.debug(
                f"Attempting to import {pkg_name} as an installed package ..."
            )
            try:
                module = importlib.import_module(pkg_name)
            except ModuleNotFoundError:
                app.logger.error(
                    f"Attempted to import module {pkg_name} (as it is not a valid file path), but it is not installed."
                )
                continue
        else:  # assume plugin is a file path
            if not os.path.exists(os.path.join(plugin, "__init__.py")):
                app.logger.error(
                    f"Plugin {plugin_name} is a valid file path, but does not contain an '__init__.py' file. Cannot load plugin {plugin_name}."
                )
                continue
            spec = importlib.util.spec_from_file_location(
                plugin_name, os.path.join(plugin, "__init__.py")
            )
            if spec is None:
                app.logger.error(
                    f"Could not load specs for plugin {plugin_name} at {plugin}."
                )
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[plugin_name] = module
            assert isinstance(spec.loader, Loader)
            spec.loader.exec_module(module)

        if module is None:
            app.logger.error(f"Plugin {plugin} could not be loaded.")
            continue

        plugin_version = getattr(module, "__version__", "0.1")
        plugin_settings = getattr(module, "__settings__", {})
        check_config_settings(app, plugin_settings)

        # Look for blueprints in the plugin's main __init__ module and register them
        plugin_blueprints = [
            getattr(module, a)
            for a in dir(module)
            if isinstance(getattr(module, a), Blueprint)
        ]
        if not plugin_blueprints:
            app.logger.warning(
                f"No blueprints found for plugin {plugin_name} at {plugin}."
            )
            continue
        for plugin_blueprint in plugin_blueprints:
            app.logger.debug(f"Registering {plugin_blueprint} ...")
            app.register_blueprint(plugin_blueprint)

        app.config["LOADED_PLUGINS"][plugin_name] = plugin_version
    app.logger.info(f"Loaded plugins: {app.config['LOADED_PLUGINS']}")
    sentry_sdk.set_context("plugins", app.config.get("LOADED_PLUGINS", {}))


def check_config_settings(app, settings: Dict[str, dict]):
    """Make sure expected config settings exist.

    For example:

        settings = {
            "MY_PLUGIN_URL": {
                "description": "URL used by my plugin for x.",
                "level": "error",
            },
            "MY_PLUGIN_TOKEN": {
                "description": "Token used by my plugin for y.",
                "level": "warning",
                "message": "Without this token, my plugin will not do y.",
                "parse_as": str,
            },
            "MY_PLUGIN_COLOR": {
                "description": "Color used to override the default plugin color.",
                "level": "info",
            },
        }

    """
    assert isinstance(settings, dict), f"{settings} should be a dict"
    for setting_name, setting_fields in settings.items():
        assert isinstance(setting_fields, dict), f"{setting_name} should be a dict"

    missing_config_settings = []
    for setting_name, setting_fields in settings.items():
        if app.config.get(setting_name) is None:
            missing_config_settings.append(setting_name)
    for setting_name in missing_config_settings:
        log_missing_config_setting(app, setting_name, settings[setting_name])


def log_missing_config_setting(app, setting_name: str, setting_fields: dict):
    """Log a message for this missing config setting.

    The logging level is taken from the 'level' key. If missing, we default to error.
    If present, we also log the 'description' and the 'message_if_missing' keys.
    """
    message_if_missing = (
        f" {setting_fields['message_if_missing']}"
        if "message_if_missing" in setting_fields
        else ""
    )
    description = (
        f" ({setting_fields['description']})" if "description" in setting_fields else ""
    )
    level = setting_fields["level"] if "level" in setting_fields else "error"
    getattr(app.logger, level)(
        f"Missing config setting '{setting_name}'{description}.{message_if_missing}",
    )
