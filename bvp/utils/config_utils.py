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


def configure_logging(app):
    """Configure and register logging"""
    app.config['LOGGER_HANDLER_POLICY'] = 'always'  # 'always' (default), 'never',  'production', 'debug'
    app.config['LOGGER_NAME'] = 'bvp'  # define which logger to use for Flask
    # For some reason, we first need to initialise Flask's logger with this so our config will take effect:
    assert app.logger
    loggingDictConfig(bvp_logging_config)


def read_config(app):
    """Read configuration from various expected sources, complain if not setup correctly. """
    if os.environ.get("BVP_ENVIRONMENT") is None:
        print('Please set/export the BVP_ENVIRONMENT variable to either "Development", "Testing", "Staging"'
              ' or "Production".')
        sys.exit(2)

    app_env = os.environ.get('BVP_ENVIRONMENT')
    app.config.from_object("bvp.utils.config_defaults.%sConfig" % app_env)

    env_config_path = "%s/%s-conf.py" % (app.root_path, app_env)
    app.config.from_pyfile(env_config_path)

    missing_settings = check_config_completeness(app)
    if len(missing_settings) > 0:
        if not os.path.exists(env_config_path):
            print("Please provide the file \"%s\" in your app directory to provide environment-specific"
                  " settings. We are missing: %s" % (env_config_path, ", ".join(missing_settings)))
        else:
            print("Missing settings: %s" % ", ".join(missing_settings))
        sys.exit(2)

    app.config["START_TIME"] = datetime.now()


def check_config_completeness(app):
    """Check if all settings we expect are not None. Return the ones that are None."""
    expected_settings = []
    for attr in [a for a in DefaultConfig.__dict__ if not a.startswith("__") and a in DefaultConfig.required]:
        if not callable(getattr(DefaultConfig, attr)):
            expected_settings.append(attr)
    return [s for s in expected_settings if app.config.get(s) is None]
