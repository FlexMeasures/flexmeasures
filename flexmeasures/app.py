"""
Starting point of the Flask application.
"""

from __future__ import annotations

import time
from copy import copy
import os
from pathlib import Path
from datetime import date

from flask import Flask, g, request
from flask.cli import load_dotenv
from flask_mail import Mail
from flask_sslify import SSLify
from flask_json import FlaskJSON
from flask_cors import CORS

from redis import Redis
from rq import Queue

from flexmeasures.data.services.job_cache import JobCache


def create(  # noqa C901
    env: str | None = None,
    path_to_config: str | None = None,
    plugins: list[str] | None = None,
) -> Flask:
    """
    Create a Flask app and configure it.

    Set the environment by setting FLEXMEASURES_ENV as environment variable (also possible in .env).
    Or, overwrite any FLEXMEASURES_ENV setting by passing an env in directly (useful for testing for instance).

    A path to a config file can be passed in (otherwise a config file will be searched in the home or instance directories).

    Also, a list of plugins can be set. Usually this works as a config setting, but this is useful for automated testing.
    """

    from flexmeasures.utils import config_defaults
    from flexmeasures.utils.config_utils import read_config, configure_logging
    from flexmeasures.utils.app_utils import set_secret_key, init_sentry
    from flexmeasures.utils.error_utils import add_basic_error_handlers

    # Create app

    configure_logging()  # do this first, see https://flask.palletsprojects.com/en/2.0.x/logging
    # we're loading dotenv files manually & early (can do Flask.run(load_dotenv=False)),
    # as we need to know the ENV now (for it to be recognised by Flask()).
    load_dotenv()
    app = Flask("flexmeasures")

    if env is not None:  # overwrite
        app.config["FLEXMEASURES_ENV"] = env
    if app.config.get("FLEXMEASURES_ENV") == "testing":
        app.testing = True
    if app.config.get("FLEXMEASURES_ENV") == "development":
        app.debug = config_defaults.DevelopmentConfig.DEBUG

    # App configuration

    read_config(app, custom_path_to_config=path_to_config)
    if plugins:
        app.config["FLEXMEASURES_PLUGINS"] += plugins
    add_basic_error_handlers(app)
    if (
        app.config.get("FLEXMEASURES_ENV") not in ("development", "documentation")
        and not app.testing
    ):
        init_sentry(app)

    app.mail = Mail(app)
    FlaskJSON(app)
    CORS(app)

    # configure Redis (for redis queue)
    if app.testing:
        from fakeredis import FakeStrictRedis

        redis_conn = FakeStrictRedis(
            host="redis", port="1234"
        )  # dummy connection details
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
    app.redis_connection = redis_conn
    app.queues = dict(
        forecasting=Queue(connection=redis_conn, name="forecasting"),
        scheduling=Queue(connection=redis_conn, name="scheduling"),
        # reporting=Queue(connection=redis_conn, name="reporting"),
        # labelling=Queue(connection=redis_conn, name="labelling"),
        # alerting=Queue(connection=redis_conn, name="alerting"),
    )
    app.job_cache = JobCache(app.redis_connection)

    # Some basic security measures

    set_secret_key(app)
    if app.config.get("SECURITY_PASSWORD_SALT", None) is None:
        app.config["SECURITY_PASSWORD_SALT"] = app.config["SECRET_KEY"]
    if app.config.get("FLEXMEASURES_FORCE_HTTPS", False):
        SSLify(app)

    # Prepare profiling, if needed

    if app.config.get("FLEXMEASURES_PROFILE_REQUESTS", False):
        Path("profile_reports").mkdir(parents=True, exist_ok=True)
        try:
            import pyinstrument  # noqa F401
        except ImportError:
            app.logger.warning(
                "FLEXMEASURES_PROFILE_REQUESTS is True, but pyinstrument not installed ― I cannot produce profiling reports for requests."
            )

    # Register database and models, including user auth security handlers

    from flexmeasures.data import register_at as register_db_at

    register_db_at(app)

    # Register Reporters and Schedulers
    from flexmeasures.utils.coding_utils import get_classes_module
    from flexmeasures.data.models import reporting, planning

    reporters = get_classes_module("flexmeasures.data.models", reporting.Reporter)
    schedulers = get_classes_module("flexmeasures.data.models", planning.Scheduler)

    app.data_generators = dict()
    app.data_generators["reporter"] = copy(
        reporters
    )  # use copy to avoid mutating app.reporters
    app.data_generators["scheduler"] = schedulers

    # add auth policy

    from flexmeasures.auth import register_at as register_auth_at

    register_auth_at(app)

    # This needs to happen here because for unknown reasons, Security(app)
    # and FlaskJSON() will set this to False on their own
    if app.config.get("FLEXMEASURES_JSON_COMPACT", False) in (
        True,
        "True",
        "true",
        "1",
        "yes",
    ):
        app.json.compact = True
    else:
        app.json.compact = False

    # Register the CLI

    from flexmeasures.cli import register_at as register_cli_at

    register_cli_at(app)

    # Register the API

    from flexmeasures.api import register_at as register_api_at

    register_api_at(app)

    # Register plugins
    # If plugins register routes, they'll have precedence over standard UI
    # routes (first registration wins). However, we want to control "/" separately.

    from flexmeasures.utils.app_utils import root_dispatcher
    from flexmeasures.utils.plugin_utils import register_plugins

    app.add_url_rule("/", view_func=root_dispatcher)
    register_plugins(app)

    # Register the UI

    from flexmeasures.ui import register_at as register_ui_at

    register_ui_at(app)

    # Global template variables for both our own templates and external templates
    @app.context_processor
    def set_global_template_variables():
        return {"queue_names": app.queues.keys()}

    # Profile endpoints (if needed, e.g. during development)

    @app.before_request
    def before_request():
        if app.config.get("FLEXMEASURES_PROFILE_REQUESTS", False):
            g.start = time.time()
            try:
                import pyinstrument  # noqa F401

                g.profiler = pyinstrument.Profiler(async_mode="disabled")
                g.profiler.start()
            except ImportError:
                pass

    @app.teardown_request
    def teardown_request(exception=None):
        if app.config.get("FLEXMEASURES_PROFILE_REQUESTS", False):
            diff = time.time() - g.start
            if all([kw not in request.url for kw in ["/static", "favicon.ico"]]):
                app.logger.info(
                    f"[PROFILE] {str(round(diff, 2)).rjust(6)} seconds to serve {request.url}."
                )
                if not hasattr(g, "profiler"):
                    return app
                g.profiler.stop()
                output_html = g.profiler.output_html(timeline=True)
                endpoint = request.endpoint
                if endpoint is None:
                    endpoint = "unknown"
                today = date.today()
                profile_filename = f"pyinstrument_{endpoint}.html"
                profile_output_path = Path(
                    "profile_reports", today.strftime("%Y-%m-%d")
                )
                profile_output_path.mkdir(parents=True, exist_ok=True)
                with open(
                    os.path.join(profile_output_path, profile_filename), "w+"
                ) as f:
                    f.write(output_html)

    return app
