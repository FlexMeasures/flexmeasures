import sys
import os.path
from logging.config import dictConfig as loggingDictConfig

from flask import Flask

from views import a1_views
from error_views import a1_error_views


DEBUG = False


def install_secret_key(app, filename='secret_key'):
    """Configure the SECRET_KEY from a file
    in the instance directory.

    If the file does not exist, print instructions
    to create it from a shell with a random key,
    then exit.
    """
    filename = os.path.join(app.instance_path, filename)
    try:
        app.config['SECRET_KEY'] = open(filename, 'rb').read()
    except IOError:
        print('Error: No secret key. Create it with:')
        if not os.path.isdir(os.path.dirname(filename)):
            print('mkdir -p', os.path.dirname(filename))
        print('head -c 24 /dev/urandom >', filename)
        sys.exit(1)


a1vpp_logging_config = {
    'version': 1,
    'formatters': {
        'default': {
            'format': '[%(asctime)s] %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]',
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
            'filename': 'a1-vpp-errors.log'
        }
    },
    'loggers': {
        'a1-vpp': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True
        },
        'werkzeug': {'propagate': True},
    }
}

if DEBUG:
    print("Initiating FileHandler logger.")
    a1vpp_logging_config["handlers"]["file"] = {
        "class": "logging.FileHandler",
        "formatter": 'default',
        "level": "WARNING",
        "filename": "a1-vpp-errors.log"
    }


APP = Flask(__name__)

install_secret_key(APP)

APP.config['SESSION_TYPE'] = 'filesystem'

APP.config['LOGGER_HANDLER_POLICY'] = 'always'  # 'always' (default), 'never',  'production', 'debug'
APP.config['LOGGER_NAME'] = 'a1-vpp'  # define which logger to use for Flask
# For some reason, we first need to initialise Flask's logger so our config will take effect:
assert APP.logger
loggingDictConfig(a1vpp_logging_config)

APP.register_blueprint(a1_views)
APP.register_blueprint(a1_error_views)


if __name__ == '__main__':
    print("Starting A1 VPP application ...")

    APP.run(debug=DEBUG)
