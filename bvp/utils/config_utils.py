import os
import sys
from datetime import datetime
from logging.config import dictConfig as loggingDictConfig
from urllib.parse import urlparse

from flask import request
from inflection import camelize

from bvp.utils.config_defaults import Config as DefaultConfig


basedir = os.path.abspath(os.path.dirname(__file__))

bvp_logging_config = {
    "version": 1,
    "formatters": {
        "default": {
            "format": "[%(asctime)s] %(levelname)s: %(message)s [log made in %(pathname)s:%(lineno)d]"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "formatter": "default",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "WARNING",
            "formatter": "default",
            "filename": "bvp-errors.log",
        },
    },
    "root": {"level": "INFO", "handlers": ["console", "file"], "propagate": True},
}


def configure_logging():
    """Configure and register logging"""
    # For some reason, we first need to initialise Flask's logger with this so our config will take effect:
    loggingDictConfig(bvp_logging_config)


def read_config(app):
    """Read configuration from various expected sources, complain if not setup correctly. """

    if app.env not in ("development", "testing", "staging", "production"):
        print(
            'Flask(bvp) environment needs to be either "development", "testing", "staging" or "production".'
        )
        sys.exit(2)

    app.config.from_object("bvp.utils.config_defaults.%sConfig" % camelize(app.env))

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
                    " in the bvp directory, and include these settings."
                    % (", ".join(missing_settings), app.env, env_config_path)
                )
            else:
                print(
                    "Missing configuration settings: %s" % ", ".join(missing_settings)
                )
            sys.exit(2)

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


def get_naming_authority() -> str:
    domain_name = urlparse(request.url).netloc
    reverse_domain_name = ".".join(domain_name.split(".")[::-1])
    return "2018-06.%s" % reverse_domain_name


def get_addressing_scheme() -> str:
    return "ea1"
