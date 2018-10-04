from flask import Flask
from flask.cli import load_dotenv
from flask_mail import Mail
from flask_sslify import SSLify
from flask_json import FlaskJSON

from bvp.utils.config_utils import read_config, configure_logging
from bvp.utils.app_utils import install_secret_key
from bvp.utils.error_utils import add_basic_error_handlers


def create(env=None) -> Flask:
    """
    Create a Flask app and configure it.
    Set the environment by setting FLASK_ENV as environment variable (also possible in .env).
    Or, overwrite any FLASK_ENV setting by passing an env in directly (useful for testing for instance).
    """

    # Create app

    configure_logging()  # do this first, see http://flask.pocoo.org/docs/dev/logging/
    # we're loading dotenv files manually & early (can do Flask.run(load_dotenv=False)),
    # as we need to know the ENV now (for it to be recognised by Flask()).
    load_dotenv()
    app = Flask("bvp")
    if env is not None:  # overwrite
        app.env = env
        if env == "testing":
            app.testing = True

    # App configuration

    read_config(app)
    if app.debug and not app.testing and not app.cli:
        print(app.config)
    add_basic_error_handlers(app)

    app.mail = Mail(app)
    FlaskJSON(app)

    # Some basic security measures

    install_secret_key(app)
    SSLify(app)

    # Register database and models, including user auth security measures

    from bvp.data import register_at as register_db_at

    register_db_at(app)

    # Register the UI

    from bvp.ui import register_at as register_ui_at

    register_ui_at(app)

    # Register the API

    from bvp.api import register_at as register_api_at

    register_api_at(app)

    if app.cli:
        with app.app_context():
            import bvp.utils.pa_ssl_cert_renewal  # noqa: F401

    return app
