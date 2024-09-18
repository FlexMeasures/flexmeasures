"""
Backoffice user interface & charting support.
"""

import os

from flask import current_app, Flask, Blueprint, send_from_directory, request
from flask_security import login_required, roles_accepted
from flask_login import current_user

import pandas as pd
import rq_dashboard
from humanize import naturaldelta

from werkzeug.exceptions import Forbidden

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

# The ui blueprint. It is registered with the Flask app (see app.py)
flexmeasures_ui = Blueprint(
    "flexmeasures_ui",
    __name__,
    static_folder="static",
    static_url_path="/ui/static",
    template_folder="templates",
)


def register_at(app: Flask):
    """This can be used to register this blueprint together with other ui-related things"""

    from flexmeasures.ui.crud.assets import AssetCrudUI
    from flexmeasures.ui.crud.users import UserCrudUI
    from flexmeasures.ui.crud.accounts import AccountCrudUI
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
    add_jinja_filters(app)
    add_jinja_variables(app)


def register_rq_dashboard(app):
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
    if app.config.get("FLEXMEASURES_MODE", "") == "demo":
        rq_dashboard.blueprint.before_request(basic_auth)
    else:
        rq_dashboard.blueprint.before_request(basic_admin_auth)

    # To set template variables, use set_global_template_variables in app.py
    app.register_blueprint(rq_dashboard.blueprint, url_prefix="/tasks")


def add_jinja_filters(app):
    from flexmeasures.ui.utils.view_utils import asset_icon_name, username, accountname

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
    app.jinja_env.filters[
        "parse_config_entry_by_account_roles"
    ] = parse_config_entry_by_account_roles
    app.jinja_env.filters[
        "find_first_applicable_config_entry"
    ] = find_first_applicable_config_entry


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
    app.jinja_env.globals["documentation_exists"] = (
        True
        if os.path.exists(
            "%s/static/documentation/html/index.html" % flexmeasures_ui.root_path
        )
        else False
    )
