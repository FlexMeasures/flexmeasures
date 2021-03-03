import os
import sys
import logging
from typing import Optional
from datetime import datetime
from logging.config import dictConfig as loggingDictConfig
from pathlib import Path

from flask import Flask
from inflection import camelize

from flexmeasures.utils.config_defaults import Config as DefaultConfig


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
    if path_to_config is not None and not os.path.exists(path_to_config):
        print(f"Cannot find config file {path_to_config}!")
        sys.exit(2)
    path_to_config_home = str(Path.home().joinpath(".flexmeasures.cfg"))
    path_to_config_instance = os.path.join(app.instance_path, "flexmeasures.cfg")
    if path_to_config is None:
        path_to_config = path_to_config_home
        if not os.path.exists(path_to_config):
            path_to_config = path_to_config_instance
    try:
        app.config.from_pyfile(path_to_config)
    except FileNotFoundError:
        pass

    # Check for missing values. Testing might affect only specific functionality (-> dev's responsibility)
    if not app.testing and app.env != "documentation":
        missing_settings = check_config_completeness(app)
        if len(missing_settings) > 0:
            if not os.path.exists(path_to_config):
                print(
                    f"Missing configuration settings: {', '.join(missing_settings)}\n"
                    f"Please provide these settings in your config file (e.g. {path_to_config_home} or {path_to_config_instance})."
                )
            else:
                print(f"Missing configuration settings: {', '.join(missing_settings)}")
            sys.exit(2)

    # Set the desired logging level on the root logger (controlling extension logging level)
    # and this app's logger.
    logging.getLogger().setLevel(app.config.get("LOGGING_LEVEL", "INFO"))
    app.logger.setLevel(app.config.get("LOGGING_LEVEL", "INFO"))
    # print("Logging level is %s" % logging.getLevelName(app.logger.level))

    app.config["START_TIME"] = datetime.utcnow()


def check_config_completeness(app):
    """Check if all settings we expect are not None. Return the ones that are None."""
    expected_settings = []
    for attr in [
        a
        for a in DefaultConfig.__dict__
        if not a.startswith("__") and a in DefaultConfig.required
    ]:
        if not callable(getattr(DefaultConfig, attr)):
            expected_settings.append(attr)
    return [s for s in expected_settings if app.config.get(s) is None]
