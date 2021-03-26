import os
import sys
import logging
from typing import Optional, List, Tuple
from datetime import datetime
from logging.config import dictConfig as loggingDictConfig
from pathlib import Path

from flask import Flask
from inflection import camelize

from flexmeasures.utils.config_defaults import (
    Config as DefaultConfig,
    required,
    warnable,
)


basedir = os.path.abspath(os.path.dirname(__file__))

flexmeasures_logging_config = {
    "version": 1,
    "formatters": {
        "default": {"format": "[FLEXMEASURES][%(asctime)s] %(levelname)s: %(message)s"},
        "detail": {
            "format": "[FLEXMEASURES][%(asctime)s] %(levelname)s: %(message)s [log made in %(pathname)s:%(lineno)d]"
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "formatter": "default",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "INFO",
            "formatter": "detail",
            "filename": basedir + "/../../flexmeasures.log",
            "maxBytes": 10_000_000,
            "backupCount": 6,
        },
    },
    "root": {"level": "INFO", "handlers": ["console", "file"], "propagate": True},
}


def configure_logging():
    """Configure and register logging"""
    loggingDictConfig(flexmeasures_logging_config)


def read_config(app: Flask, path_to_config: Optional[str]):
    """Read configuration from various expected sources, complain if not setup correctly. """

    if app.env not in (
        "documentation",
        "development",
        "testing",
        "staging",
        "production",
    ):
        print(
            'Flask(flexmeasures) environment needs to be either "documentation", "development", "testing", "staging" or "production".'
        )
        sys.exit(2)

    # Load default config settings
    app.config.from_object(
        "flexmeasures.utils.config_defaults.%sConfig" % camelize(app.env)
    )

    # Now read user config, if possible. If no explicit path is given, try home dir first, then instance dir
    path_to_config_home = str(Path.home().joinpath(".flexmeasures.cfg"))
    path_to_config_instance = os.path.join(app.instance_path, "flexmeasures.cfg")
    if not app.testing:
        used_path_to_config = read_custom_config(
            app, path_to_config, path_to_config_home, path_to_config_instance
        )

    # Check for missing values.
    # Testing might affect only specific functionality (-> dev's responsibility)
    # Documentation runs fine without them.
    if not app.testing and app.env != "documentation":
        if not are_required_settings_complete(app):
            if not os.path.exists(used_path_to_config):
                print(
                    f"You can provide these settings ― as environment variables or in your config file (e.g. {path_to_config_home} or {path_to_config_instance})."
                )
            else:
                print(
                    f"Please provide these settings ― as environment variables or in your config file ({used_path_to_config})."
                )
            sys.exit(2)
        missing_fields, config_warnings = get_config_warnings(app)
        if len(config_warnings) > 0:
            for warning in config_warnings:
                print(f"Warning: {warning}")
            print(f"You might consider setting {', '.join(missing_fields)}.")

    # Set the desired logging level on the root logger (controlling extension logging level)
    # and this app's logger.
    logging.getLogger().setLevel(app.config.get("LOGGING_LEVEL", "INFO"))
    app.logger.setLevel(app.config.get("LOGGING_LEVEL", "INFO"))
    # print("Logging level is %s" % logging.getLevelName(app.logger.level))

    app.config["START_TIME"] = datetime.utcnow()


def read_custom_config(
    app, suggested_path_to_config, path_to_config_home, path_to_config_instance
) -> str:
    """ read in a custom config file or env vars. Return the path to the config file."""
    if suggested_path_to_config is not None and not os.path.exists(
        suggested_path_to_config
    ):
        print(f"Cannot find config file {suggested_path_to_config}!")
        sys.exit(2)
    if suggested_path_to_config is None:
        path_to_config = path_to_config_home
        if not os.path.exists(path_to_config):
            path_to_config = path_to_config_instance
    else:
        path_to_config = suggested_path_to_config
    try:
        app.config.from_pyfile(path_to_config)
    except FileNotFoundError:
        pass
    # Finally, all required varaiables can be set as env var:
    for req_var in required:
        app.config[req_var] = os.getenv(req_var, app.config.get(req_var, None))
    return path_to_config


def are_required_settings_complete(app) -> bool:
    """
    Check if all settings we expect are not None. Return False if they are not.
    Printout helpful advice.
    """
    expected_settings = [s for s in get_configuration_keys(app) if s in required]
    missing_settings = [s for s in expected_settings if app.config.get(s) is None]
    if len(missing_settings) > 0:
        print(
            f"Missing the required configuration settings: {', '.join(missing_settings)}"
        )
        return False
    return True


def get_config_warnings(app) -> Tuple[List[str], List[str]]:
    """return missing settings and the warnings for them."""
    missing_settings = []
    config_warnings = []
    for setting, warning in warnable.items():
        if app.config.get(setting) is None:
            missing_settings.append(setting)
            config_warnings.append(warning)
    config_warnings = list(set(config_warnings))
    return missing_settings, config_warnings


def get_configuration_keys(app) -> List[str]:
    """
    Collect all members of DefaultConfig who are not in-built fields or callables.
    """
    return [
        a
        for a in DefaultConfig.__dict__
        if not a.startswith("__") and not callable(getattr(DefaultConfig, a))
    ]
