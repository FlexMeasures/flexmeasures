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


flexmeasures_logging_config = {
    "version": 1,
    "formatters": {
        "default": {"format": "[FLEXMEASURES][%(asctime)s] %(levelname)s: %(message)s"},
        "detail": {
            "format": "[FLEXMEASURES][%(asctime)s] %(levelname)s: %(message)s [logged in %(pathname)s:%(lineno)d]"
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
            "filename": "flexmeasures.log",
            "maxBytes": 10_000_000,
            "backupCount": 6,
        },
    },
    "root": {"level": "INFO", "handlers": ["console", "file"], "propagate": True},
}


def configure_logging():
    """Configure and register logging"""
    loggingDictConfig(flexmeasures_logging_config)


def check_app_env(env: Optional[str]):
    if env not in (
        "documentation",
        "development",
        "testing",
        "staging",
        "production",
    ):
        print(
            f'Flask(flexmeasures) environment needs to be either "documentation", "development", "testing", "staging" or "production". It currently is "{env}".'
        )
        sys.exit(2)


def read_config(app: Flask, custom_path_to_config: Optional[str]):
    """Read configuration from various expected sources, complain if not setup correctly."""

    check_app_env(app.env)

    # First, load default config settings
    app.config.from_object(
        "flexmeasures.utils.config_defaults.%sConfig" % camelize(app.env)
    )

    # Now, potentially overwrite those from config file or environment variables

    # These two locations are possible (besides the custom path)
    path_to_config_home = str(Path.home().joinpath(".flexmeasures.cfg"))
    path_to_config_instance = os.path.join(app.instance_path, "flexmeasures.cfg")

    # Don't overwrite when testing (that should run completely on defaults)
    if not app.testing:
        used_path_to_config = read_custom_config(
            app, custom_path_to_config, path_to_config_home, path_to_config_instance
        )
        read_required_env_vars(app)

    # Check for missing values.
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
    app: Flask, suggested_path_to_config, path_to_config_home, path_to_config_instance
) -> str:
    """
    Read in a custom config file and env vars.
    For the config, there are two fallback options, tried in a specific order:
    If no custom path is suggested, we'll try the path in the home dir first,
    then in the instance dir.

    Return the path to the config file.
    """
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
    app.logger.info(f"Loading config from {path_to_config} ...")
    try:
        app.config.from_pyfile(path_to_config)
    except FileNotFoundError:
        app.logger.warning(
            f"File {path_to_config} could not be found! (work dir is {os.getcwd()})"
        )
        app.logger.warning(f"File exists: {os.path.exists(path_to_config)}")
    return path_to_config


def read_required_env_vars(app: Flask):
    """All required variables and the plugins can be set as env var"""
    for var in required:
        app.config[var] = os.getenv(var, app.config.get(var, None))


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
