import sys
import os.path
from logging.config import dictConfig as loggingDictConfig

from flask import Flask
from flask import send_from_directory

from views import a1_views
from error_views import a1_error_views

"""
Prepare the Flask application object, configure logger and session.
"""


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

APP = Flask(__name__)

install_secret_key(APP)

APP.config['SESSION_TYPE'] = 'filesystem'

APP.config['LOGGER_HANDLER_POLICY'] = 'always'  # 'always' (default), 'never',  'production', 'debug'
APP.config['LOGGER_NAME'] = 'a1-vpp'  # define which logger to use for Flask
# For some reason, we first need to initialise Flask's logger so our config will take effect:
assert APP.logger
loggingDictConfig(a1vpp_logging_config)


@APP.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(APP.root_path, 'public'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

APP.register_blueprint(a1_views)
APP.register_blueprint(a1_error_views)
