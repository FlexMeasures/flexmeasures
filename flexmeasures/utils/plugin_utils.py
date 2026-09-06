"""
Utils for registering FlexMeasures plugins
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
from importlib.abc import Loader
from types import ModuleType

import sentry_sdk
from flask import Flask, Blueprint

from flexmeasures.utils.coding_utils import get_classes_module


def is_written_as_path(plugin: str) -> bool:
    """Whether this FLEXMEASURES_PLUGINS entry is spelled out as a file path.

    A bare name like ``my_plugin`` is not: it may well name an installed package.
    """
    separators = [sep for sep in (os.sep, os.altsep) if sep is not None]
    return os.path.isabs(plugin) or any(sep in plugin for sep in separators)


def find_importable_package(pkg_name: str) -> importlib.machinery.ModuleSpec | None:
    """Find the spec of an importable package, if there is one.

    Namespace packages are ignored: a folder without an ``__init__.py`` is importable,
    but accepting it here would shadow the clearer error that the file path branch of
    ``register_plugins`` reports for such a folder.
    """
    try:
        spec = importlib.util.find_spec(pkg_name)
    except (ImportError, ValueError):
        # ImportError: a dotted name whose parent package is missing.
        # ValueError: a name that is in sys.modules without a spec.
        return None
    if spec is None or spec.origin is None:
        return None
    return spec


def register_plugins(app: Flask):  # noqa: C901
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

    An entry that is not spelled out as a file path is imported as an installed package
    if one goes by that name, even when a folder of the same name sits in the working
    directory. To load such a folder instead, spell out its path (e.g. ``./my_plugin``).
    """
    plugins = app.config.get("FLEXMEASURES_PLUGINS", [])
    if isinstance(plugins, str):
        plugins = [
            plugin.strip() for plugin in plugins.split(",") if len(plugin.strip()) > 0
        ]
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
        pkg_name = os.path.split(plugin)[
            -1
        ]  # rule out attempts for relative package imports
        # An installed package wins from a folder of the same name in the working directory,
        # unless the entry is spelled out as a file path. Loading such a folder by path would
        # execute its __init__.py a second time, under a new module object, while submodules
        # imported by the first execution keep referring to the old one — so, for instance,
        # routes end up on a Blueprint that is never registered. See GH issue #2415.
        prefer_package = not is_written_as_path(plugin) and (
            find_importable_package(pkg_name) is not None
        )
        if not os.path.exists(plugin) or prefer_package:  # assume plugin is a package
            if prefer_package and os.path.exists(plugin):
                app.logger.debug(
                    f"Loading plugin {plugin_name} as an installed package,"
                    f" ignoring the folder of the same name in the working directory."
                    f" Spell out its path (e.g. '.{os.sep}{plugin}') to load that folder instead."
                )
            app.logger.debug(
                f"Attempting to import {pkg_name} as an installed package ..."
            )
            try:
                module = importlib.import_module(pkg_name)
            except ModuleNotFoundError:
                app.logger.error(
                    f'Attempted to import module {pkg_name} (as it is not a valid file path), but it is not installed. Make sure you use a comma-separated list of modules, e.g. "module1,module2".'
                )
                continue
        else:  # assume plugin is a file path
            if not is_written_as_path(plugin):
                app.logger.warning(
                    f"Loading plugin {plugin_name} from the folder of that name in the working directory,"
                    f" as no installed package goes by that name."
                    f" Spell out its path (e.g. '.{os.sep}{plugin}') to make this explicit."
                )
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

        # Load reporters and schedulers
        from flexmeasures.data.models.forecasting import Forecaster
        from flexmeasures.data.models.reporting import Reporter
        from flexmeasures.data.models.planning import Scheduler

        plugin_forecasters = get_classes_module(module.__name__, Forecaster)
        plugin_reporters = get_classes_module(module.__name__, Reporter)
        plugin_schedulers = get_classes_module(module.__name__, Scheduler)

        # add DataGenerators
        if plugin_forecasters:
            app.data_generators["forecaster"].update(plugin_forecasters)
        if plugin_reporters:
            app.data_generators["reporter"].update(plugin_reporters)
        if plugin_schedulers:
            app.data_generators["scheduler"].update(plugin_schedulers)

        app.config["LOADED_PLUGINS"][plugin_name] = plugin_version
    app.logger.info(f"Loaded plugins: {app.config['LOADED_PLUGINS']}")
    sentry_sdk.set_context("plugins", app.config.get("LOADED_PLUGINS", {}))


def check_config_settings(app, settings: dict[str, dict]):
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

    # Check config settings are in dict form, after possibly converting them from module variables
    if isinstance(settings, ModuleType):
        settings = {
            setting: settings.__dict__[setting]
            for setting in dir(settings)
            if not setting.startswith("__")
        }
    assert isinstance(settings, dict), f"{type(settings)} should be a dict"
    for setting_name, setting_fields in settings.items():
        assert isinstance(setting_fields, dict), f"{setting_name} should be a dict"

    missing_config_settings = []
    config_settings_with_wrong_type = []
    for setting_name, setting_fields in settings.items():
        setting = app.config.get(setting_name)
        if setting is None:
            missing_config_settings.append(setting_name)
        elif "parse_as" in setting_fields and not isinstance(
            setting, setting_fields["parse_as"]
        ):
            config_settings_with_wrong_type.append((setting_name, setting))
    for setting_name, setting in config_settings_with_wrong_type:
        log_wrong_type_for_config_setting(
            app, setting_name, settings[setting_name], type(setting)
        )
    for setting_name in missing_config_settings:
        log_missing_config_setting(app, setting_name, settings[setting_name])


def log_wrong_type_for_config_setting(
    app, setting_name: str, setting_fields: dict, setting_type: type
):
    """Log a message for this config setting that has the wrong type."""
    app.logger.warning(
        f"Config setting '{setting_name}' is a {setting_type} whereas a {setting_fields['parse_as']} was expected."
    )


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
    if not hasattr(app.logger, level):
        app.logger.warning(
            f"Unrecognized logger level '{level}' for config setting '{setting_name}'."
        )
        level = "error"
    getattr(app.logger, level)(
        f"Missing config setting '{setting_name}'{description}.{message_if_missing}",
    )
