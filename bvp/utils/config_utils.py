import os
import sys
from datetime import datetime
from logging.config import dictConfig as loggingDictConfig

from bvp.utils.config_defaults import Config as DefaultConfig


basedir = os.path.abspath(os.path.dirname(__file__))

bvp_logging_config = {
    'version': 1,
    'formatters': {
        'default': {
            'format': '[%(asctime)s] %(levelname)s: %(message)s [log made in %(pathname)s:%(lineno)d]',
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'stream': sys.stdout,
            'formatter': 'default'
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'level': 'WARNING',
            'formatter': 'default',
            'filename': 'bvp-errors.log'
        }
    },
    'loggers': {
        'bvp': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True
        },
        'werkzeug': {'propagate': True},
    }
}


def configure_logging():
    """Configure and register logging"""
    # For some reason, we first need to initialise Flask's logger with this so our config will take effect:
    loggingDictConfig(bvp_logging_config)


def read_config(app, environment=None):
    """Read configuration from various expected sources, complain if not setup correctly. """

    if environment is None:
        environment = os.environ.get('BVP_ENVIRONMENT')

    if environment is None:
        print('Please set/export the BVP_ENVIRONMENT variable to either "Development", "Testing", "Staging"'
              ' or "Production".')
        sys.exit(2)

    app.config.from_object("bvp.utils.config_defaults.%sConfig" % environment)

    path_to_file = app.root_path
    if environment == "Testing":
        path_to_file += "/tests"
    env_config_path = "%s/%sConfig.py" % (path_to_file, environment)
    app.config.from_pyfile(env_config_path)

    missing_settings = check_config_completeness(app)
    if len(missing_settings) > 0:
        if not os.path.exists(env_config_path):
            print("Please provide the file \"%s\" in your app directory to provide environment-specific"
                  " settings. We are missing: %s" % (env_config_path, ", ".join(missing_settings)))
        else:
            print("Missing settings: %s" % ", ".join(missing_settings))
        sys.exit(2)

    app.config["START_TIME"] = datetime.utcnow()


def check_config_completeness(app):
    """Check if all settings we expect are not None. Return the ones that are None."""
    expected_settings = []
    for attr in [a for a in DefaultConfig.__dict__ if not a.startswith("__") and a in DefaultConfig.required]:
        if not callable(getattr(DefaultConfig, attr)):
            expected_settings.append(attr)
    return [s for s in expected_settings if app.config.get(s) is None]
