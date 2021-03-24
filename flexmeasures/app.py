# flake8: noqa: E402
import os
import time
from typing import Optional

from flask import Flask, g, request
from flask.cli import load_dotenv
from flask_mail import Mail
from flask_sslify import SSLify
from flask_json import FlaskJSON
from flask_cors import CORS

from redis import Redis
from rq import Queue


def create(env: Optional[str] = None, path_to_config: Optional[str] = None) -> Flask:
    """
    Create a Flask app and configure it.

    Set the environment by setting FLASK_ENV as environment variable (also possible in .env).
    Or, overwrite any FLASK_ENV setting by passing an env in directly (useful for testing for instance).

    A path to a config file can be passed in (otherwise a config file will be searched in the home or instance directories)
    """

    from flexmeasures.utils import config_defaults
    from flexmeasures.utils.config_utils import read_config, configure_logging
    from flexmeasures.utils.app_utils import set_secret_key
    from flexmeasures.utils.error_utils import add_basic_error_handlers

    # Create app

    configure_logging()  # do this first, see http://flask.pocoo.org/docs/dev/logging/
    # we're loading dotenv files manually & early (can do Flask.run(load_dotenv=False)),
    # as we need to know the ENV now (for it to be recognised by Flask()).
    load_dotenv()
    app = Flask("flexmeasures")
    if env is not None:  # overwrite
        app.env = env
        if env == "testing":
            app.testing = True
        if env == "development":
            app.debug = config_defaults.DevelopmentConfig.DEBUG

    # App configuration

    read_config(app, path_to_config=path_to_config)
    add_basic_error_handlers(app)

    app.mail = Mail(app)
    FlaskJSON(app)
    cors = CORS(app)

    # configure Redis (for redis queue)
    if app.testing:
        from fakeredis import FakeStrictRedis

        app.queues = dict(
            forecasting=Queue(connection=FakeStrictRedis(), name="forecasting"),
            scheduling=Queue(connection=FakeStrictRedis(), name="scheduling"),
        )
    else:
        redis_conn = Redis(
            app.config["FLEXMEASURES_REDIS_URL"],
            port=app.config["FLEXMEASURES_REDIS_PORT"],
            db=app.config["FLEXMEASURES_REDIS_DB_NR"],
            password=app.config["FLEXMEASURES_REDIS_PASSWORD"],
        )
        """ FWIW, you could use redislite like this (not on non-recent os.name=="nt" systems or PA, sadly):
            from redislite import Redis
            redis_conn = Redis("MY-DB-NAME", unix_socket_path="/tmp/my-redis.socket",
            )
        """
        app.queues = dict(
            forecasting=Queue(connection=redis_conn, name="forecasting"),
            scheduling=Queue(connection=redis_conn, name="scheduling"),
        )

    # Some basic security measures

    if not app.env == "documentation":
        set_secret_key(app)
        if app.config.get("SECURITY_PASSWORD_SALT", None) is None:
            app.config["SECURITY_PASSWORD_SALT"] = app.config["SECRET_KEY"]
    if not app.env in ("documentation", "development"):
        SSLify(app)

    # Register database and models, including user auth security handlers

    from flexmeasures.data import register_at as register_db_at

    register_db_at(app)

    # Register the API

    from flexmeasures.api import register_at as register_api_at

    register_api_at(app)

    # Register the UI

    from flexmeasures.ui import register_at as register_ui_at

    register_ui_at(app)

    # Profile endpoints (if needed, e.g. during development)
    @app.before_request
    def before_request():
        if app.config.get("FLEXMEASURES_PROFILE_REQUESTS", False):
            g.start = time.time()

    @app.teardown_request
    def teardown_request(exception=None):
        if app.config.get("FLEXMEASURES_PROFILE_REQUESTS", False):
            diff = time.time() - g.start
            if all([kw not in request.url for kw in ["/static", "favicon.ico"]]):
                app.logger.info(
                    f"[PROFILE] {str(round(diff, 2)).rjust(6)} seconds to serve {request.url}."
                )

    return app
