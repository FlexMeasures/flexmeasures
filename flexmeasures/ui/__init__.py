"""
Backoffice user interface & charting support.
"""

import json
import os
import threading
from datetime import date, datetime

from flask import current_app, Flask, Blueprint, send_from_directory, request
from flask_security import login_required, roles_accepted
from flask_login import current_user

import pandas as pd
import rq_dashboard
from humanize import naturaldelta

from werkzeug.exceptions import Forbidden

from flexmeasures.auth import policy as auth_policy
from flexmeasures.auth.policy import ADMIN_ROLE, ADMIN_READER_ROLE
from flexmeasures.utils.flexmeasures_inflection import (
    capitalize,
    parameterize,
    pluralize,
)
from flexmeasures.utils.time_utils import (
    localized_datetime_str,
    naturalized_datetime_str,
    to_utc_timestamp,
)
from flexmeasures.utils.app_utils import (
    parse_config_entry_by_account_roles,
    find_first_applicable_config_entry,
)
from flexmeasures.ui.utils.vendor_assets import (
    APP_EXTENSION,
    active_libraries,
    fetch_unless_fetching,
    fetched_before,
    libraries_with_overrides,
    missing_files,
    unhashed_libraries,
    vendor_attrs,
    vendor_url,
)


class UIBlueprint(Blueprint):
    """A blueprint whose vendored files, under static/vendor/<lib>/<version>/, browsers may keep for a year."""

    def send_static_file(self, filename: str):
        response = super().send_static_file(filename)
        parts = filename.split("/")
        libraries = active_libraries()
        # A new version of a library gets a new path, so a cached copy is never stale.
        if (
            len(parts) > 3
            and parts[0] == "vendor"
            and parts[1] in libraries
            and libraries[parts[1]].version == parts[2]
        ):
            response.cache_control.max_age = 31536000
            response.cache_control.immutable = True
        return response


# The ui blueprint. It is registered with the Flask app (see app.py)
flexmeasures_ui = UIBlueprint(
    "flexmeasures_ui",
    __name__,
    static_folder="static",
    static_url_path="/ui/static",
    template_folder="templates",
)


def register_at(app: Flask):
    """This can be used to register this blueprint together with other ui-related things"""

    from flexmeasures.ui.views.assets import AssetCrudUI
    from flexmeasures.ui.views.users.views import UserCrudUI
    from flexmeasures.ui.views.accounts import AccountCrudUI
    from flexmeasures.ui.views.sensors import SensorUI
    from flexmeasures.ui.utils.color_defaults import get_color_settings

    AssetCrudUI.register(app)
    UserCrudUI.register(app)
    SensorUI.register(app)
    AccountCrudUI.register(app)

    import flexmeasures.ui.views  # noqa: F401 this is necessary to load the views

    app.register_blueprint(
        flexmeasures_ui
    )  # now registering the blueprint will affect all views

    register_rq_dashboard(app)

    # Injects Flexmeasures default colors into all templates
    @app.context_processor
    def inject_global_vars():
        return get_color_settings(None)

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            flexmeasures_ui.static_folder,
            "favicon.ico",
            mimetype="image/vnd.microsoft.icon",
        )

    from flexmeasures.ui.error_handlers import add_html_error_views

    add_html_error_views(app)
    load_vendor_libraries(app)
    add_jinja_filters(app)
    add_jinja_variables(app)
    log_where_vendor_files_load_from(app)
    fetch_vendor_files_on_first_request(app)


def load_vendor_libraries(app: Flask):
    """Settle which versions of the UI's libraries the app loads, applying the FLEXMEASURES_JS_VERSIONS setting."""
    app.extensions[APP_EXTENSION] = libraries_with_overrides(
        app.config.get("FLEXMEASURES_JS_VERSIONS")
    )


def log_where_vendor_files_load_from(app: Flask):
    """Tell hosts whether browsers load the UI's libraries from CDNs, and how to serve them from FlexMeasures instead."""
    libraries = app.extensions[APP_EXTENSION]
    missing = missing_files(libraries)
    if missing and app.config.get("FLEXMEASURES_FETCH_UI_LIBRARIES"):
        app.logger.info(
            f"{len(missing)} file(s) of the UI's libraries were not fetched yet, so browsers load them from CDNs. "
            "FlexMeasures fetches them in the background once it serves its first request."
        )
    elif missing:
        # Files fetched before, but missing now, most likely belong to versions which an upgrade bumped.
        log = app.logger.warning if fetched_before() else app.logger.info
        log(
            f"{len(missing)} file(s) of the UI's libraries were not fetched, so browsers load them from CDNs. "
            "To serve them from FlexMeasures, for example without internet access, run: python -m flexmeasures.ui.utils.fetch_vendor_assets"
        )
    for key in unhashed_libraries(libraries):
        version = libraries[key].version
        app.logger.warning(
            f"FLEXMEASURES_JS_VERSIONS sets {key} to {version} without hashes, so browsers load it from its CDN without checking it, and it is not fetched. "
            f"To have it checked, set the hashes printed by: python -m flexmeasures.ui.utils.fetch_vendor_assets --print-hashes {key} --version {version}"
        )


def fetch_vendor_files_on_first_request(app: Flask):
    """Have the first request which a process serves start fetching the UI's missing library files, in the background.

    Only web processes serve requests, so CLI commands and job workers never fetch.
    The request does not wait for the fetch, and browsers load the files from CDNs until they are fetched.
    Of the web processes on a host, only the first one to get the lock fetches.
    """
    if not app.config.get("FLEXMEASURES_FETCH_UI_LIBRARIES"):
        return
    libraries = app.extensions[APP_EXTENSION]
    # Each web process has its own copy of this, also when gunicorn forks them from a process which loaded the app.
    started = threading.Lock()

    @app.before_request
    def start_fetching_vendor_files():
        if not started.acquire(blocking=False):
            return
        thread = threading.Thread(
            target=_fetch_vendor_files,
            args=(app, libraries),
            name="fetch-ui-libraries",
            daemon=True,
        )
        app.extensions["flexmeasures_vendor_fetch"] = thread
        thread.start()


def _fetch_vendor_files(app: Flask, libraries):
    try:
        written = fetch_unless_fetching(libraries)
    except (OSError, ValueError) as exc:
        app.logger.warning(
            f"Could not fetch the UI's libraries, so browsers keep loading them from CDNs: {exc}. "
            "To fetch them by hand, run: python -m flexmeasures.ui.utils.fetch_vendor_assets"
        )
        return
    if written:
        app.logger.info(
            f"Fetched {written} file(s) of the UI's libraries, which FlexMeasures serves itself from now on."
        )


def _tolerate_non_json_job_data():
    """Let rq-dashboard render jobs whose meta data is not JSON-serializable.

    rq-dashboard serializes a job's meta data with a plain ``json.dumps(job.get_meta())``
    (no ``default=``), so a job carrying e.g. a datetime or an exception in its meta data
    makes its detail page fail with a 500. We patch the module's ``json`` reference with a
    shim that falls back to a readable representation instead.

    See https://github.com/Parallels/rq-dashboard/issues/510
    """

    def default(value):
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    class TolerantJson:
        def __getattr__(self, name):
            return getattr(json, name)

        @staticmethod
        def dumps(obj, **kwargs):
            kwargs.setdefault("default", default)
            return json.dumps(obj, **kwargs)

    rq_dashboard.web.json = TolerantJson()


def register_rq_dashboard(app):
    _tolerate_non_json_job_data()
    app.config.update(
        RQ_DASHBOARD_REDIS_URL=[
            "redis://:%s@%s:%s/%s"
            % (
                app.config.get("FLEXMEASURES_REDIS_PASSWORD", ""),
                app.config.get("FLEXMEASURES_REDIS_URL", ""),
                app.config.get("FLEXMEASURES_REDIS_PORT", ""),
                app.config.get("FLEXMEASURES_REDIS_DB_NR", ""),
            ),
            # it is possible to add additional rq instances to this list
        ]
    )

    @login_required
    def basic_auth():
        """Ensure basic authorization."""
        return

    @login_required
    @roles_accepted(ADMIN_ROLE, ADMIN_READER_ROLE)
    def basic_admin_auth():
        """Ensure basic admin authorization."""

        if (
            current_user.has_role(ADMIN_READER_ROLE)
            and (request.method != "GET")
            and ("requeue" not in request.path)
        ):
            raise Forbidden(
                f"User with `{ADMIN_READER_ROLE}` role is only allowed to list/inspect tasks, queues and workers. Edition or deletion operations are forbidden."
            )

        return

    # Logged-in users can view queues on the demo server, but only admins can view them on other servers
    if app.config.get("FLEXMEASURES_ENV") != "documentation":
        if app.config.get("FLEXMEASURES_MODE", "") == "demo":
            rq_dashboard.blueprint.before_request(basic_auth)
        else:
            rq_dashboard.blueprint.before_request(basic_admin_auth)

    # To set template variables, use set_global_template_variables in app.py
    app.register_blueprint(rq_dashboard.blueprint, url_prefix="/tasks")


def add_jinja_filters(app):
    from flexmeasures.ui.utils.view_utils import asset_icon_name, username, accountname
    from flexmeasures.data.models.charts.belief_charts import (
        determine_shared_sensor_type,
    )

    def shared_sensor_type(sensors):
        """Mirror the Vega-Lite y-axis title logic: if all sensors share a
        sensor type use it, otherwise derive the dimension from the shared unit
        (e.g. a group of kW sensors becomes "power").

        ``sensor_type`` is normally set lazily inside the chart methods, so we
        populate it here (as ``get_attribute("sensor_type", name)``) before
        delegating to the shared helper.
        """
        sensors = list(sensors)
        for sensor in sensors:
            sensor.sensor_type = sensor.get_attribute("sensor_type", sensor.name)
        return determine_shared_sensor_type(sensors)

    app.jinja_env.filters["zip"] = zip  # Allow zip function in templates
    app.jinja_env.add_extension(
        "jinja2.ext.do"
    )  # Allow expression statements (e.g. for modifying lists)
    app.jinja_env.filters["localized_datetime"] = localized_datetime_str
    app.jinja_env.filters["naturalized_datetime"] = naturalized_datetime_str
    app.jinja_env.filters["to_utc_timestamp"] = to_utc_timestamp
    app.jinja_env.filters["naturalized_timedelta"] = naturaldelta
    app.jinja_env.filters["capitalize"] = capitalize
    app.jinja_env.filters["pluralize"] = pluralize
    app.jinja_env.filters["parameterize"] = parameterize
    app.jinja_env.filters["shared_sensor_type"] = shared_sensor_type
    app.jinja_env.filters["isnull"] = pd.isnull
    app.jinja_env.filters["hide_nan_if_desired"] = lambda x: (
        ""
        if x in ("nan", "nan%", "NAN")
        and current_app.config.get("FLEXMEASURES_HIDE_NAN_IN_UI", False)
        else x
    )
    app.jinja_env.filters["asset_icon"] = asset_icon_name
    app.jinja_env.filters["username"] = username
    app.jinja_env.filters["accountname"] = accountname
    app.jinja_env.filters["parse_config_entry_by_account_roles"] = (
        parse_config_entry_by_account_roles
    )
    app.jinja_env.filters["find_first_applicable_config_entry"] = (
        find_first_applicable_config_entry
    )


def add_jinja_variables(app):
    # Set variables for Jinja template context
    for v, d in (
        ("FLEXMEASURES_MODE", ""),
        ("FLEXMEASURES_PLATFORM_NAME", ""),
        ("FLEXMEASURES_MENU_LISTED_VIEWS", []),
        ("FLEXMEASURES_MENU_LISTED_VIEW_ICONS", {}),
        ("FLEXMEASURES_MENU_LISTED_VIEW_TITLES", {}),
        ("FLEXMEASURES_PUBLIC_DEMO_CREDENTIALS", ""),
    ):
        app.jinja_env.globals[v] = app.config.get(v, d)
    # A global rather than a per-render variable, so pages rendered without render_flexmeasures_template (e.g. login, errors) also get it.
    app.jinja_env.globals["js_versions"] = {
        key: library.version for key, library in app.extensions[APP_EXTENSION].items()
    }
    app.jinja_env.globals["vendor_url"] = vendor_url
    app.jinja_env.globals["vendor_attrs"] = vendor_attrs
    app.jinja_env.globals["sphinx_docs_exist"] = (
        True
        if os.path.exists(
            "%s/static/documentation/html/index.html" % flexmeasures_ui.root_path
        )
        else False
    )
    app.jinja_env.globals["openapi_docs_exist"] = (
        True
        if os.path.exists("%s/static/openapi-specs.json" % flexmeasures_ui.root_path)
        else False
    )

    for role_name in (
        "ADMIN_ROLE",
        "ADMIN_READER_ROLE",
        "ACCOUNT_ADMIN_ROLE",
        "CONSULTANT_ROLE",
    ):
        app.jinja_env.globals[role_name] = auth_policy.__dict__[role_name]
