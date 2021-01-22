import os
import sys
import logging
from datetime import datetime
from logging.config import dictConfig as loggingDictConfig

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


def read_config(app):
    """Read configuration from various expected sources, complain if not setup correctly. """

    if app.env not in ("development", "testing", "staging", "production"):
        print(
            'Flask(flexmeasures) environment needs to be either "development", "testing", "staging" or "production".'
        )
        sys.exit(2)

    app.config.from_object(
        "flexmeasures.utils.config_defaults.%sConfig" % camelize(app.env)
    )

    env_config_path = "%s/%s_config.py" % (app.root_path, app.env)

    try:
        app.config.from_pyfile(env_config_path)
    except FileNotFoundError:
        pass

    # Check for missing values. Testing might affect only specific functionality (-> dev's responsibility)
    if not app.testing:
        missing_settings = check_config_completeness(app)
        if len(missing_settings) > 0:
            if not os.path.exists(env_config_path):
                print(
                    'Missing configuration settings: %s\nAs FLASK_ENV=%s, please provide the file "%s"'
                    " in the flexmeasures directory, and include these settings."
                    % (", ".join(missing_settings), app.env, env_config_path)
                )
            else:
                print(
                    "Missing configuration settings: %s" % ", ".join(missing_settings)
                )
            sys.exit(2)

    # Set the desired logging level on the root logger (controlling extension logging level)
    # and this app's logger.
    logging.getLogger().setLevel(app.config.get("LOGGING_LEVEL"))
    app.logger.setLevel(app.config.get("LOGGING_LEVEL"))
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
