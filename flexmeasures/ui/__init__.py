import os

from flask import current_app, Flask, Blueprint
from flask.blueprints import BlueprintSetupState
from flask import send_from_directory
from flask_security import login_required, roles_accepted
import numpy as np
import rq_dashboard
from humanize import naturaldelta

from flexmeasures.utils.flexmeasures_inflection import (
    capitalize,
    parameterize,
)
from flexmeasures.utils.time_utils import (
    localized_datetime_str,
    naturalized_datetime_str,
)
from flexmeasures.api.v2_0 import flexmeasures_api as flexmeasures_api_v2_0

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

    AssetCrudUI.register(app)
    UserCrudUI.register(app)

    import flexmeasures.ui.views  # noqa: F401 this is necessary to load the views

    app.register_blueprint(
        flexmeasures_ui
    )  # now registering the blueprint will affect all views

    register_rq_dashboard(app)

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

    # Add our chart endpoint to the Api 2.0 blueprint.
    # This lets it show up in the API list twice, but that seems to be the best way for now (see below).
    # Also, we'll reconsider where these charts endpoints should really live when we make more.
    from flexmeasures.ui.views.charts import get_power_chart

    # We cannot call this directly on the blueprint, as that only defers to registration.
    # Re-registering the blueprint leads to all endpoints being listed twice.
    blueprint_state = BlueprintSetupState(
        flexmeasures_api_v2_0,
        app,
        {"url_prefix": "/api/v2_0"},
        first_registration=False,
    )
    blueprint_state.add_url_rule("/charts/power", None, get_power_chart)


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
    @roles_accepted("admin")
    def basic_admin_auth():
        """Ensure basic admin authorization."""
        return

    # Logged in users can view queues on the demo server, but only admins can view them on other servers
    if app.config.get("FLEXMEASURES_MODE", "") == "demo":
        rq_dashboard.blueprint.before_request(basic_auth)
    else:
        rq_dashboard.blueprint.before_request(basic_admin_auth)

    # Todo: rq dashboard has no way of passing FlexMeasures template variables, so how to conditionally disable menu items?
    app.register_blueprint(rq_dashboard.blueprint, url_prefix="/tasks")


def add_jinja_filters(app):
    from flexmeasures.ui.utils.view_utils import asset_icon_name, username

    app.jinja_env.filters["zip"] = zip  # Allow zip function in templates
    app.jinja_env.add_extension(
        "jinja2.ext.do"
    )  # Allow expression statements (e.g. for modifying lists)
    app.jinja_env.filters["localized_datetime"] = localized_datetime_str
    app.jinja_env.filters["naturalized_datetime"] = naturalized_datetime_str
    app.jinja_env.filters["naturalized_timedelta"] = naturaldelta
    app.jinja_env.filters["capitalize"] = capitalize
    app.jinja_env.filters["parameterize"] = parameterize
    app.jinja_env.filters["isnan"] = np.isnan
    app.jinja_env.filters["hide_nan_if_desired"] = (
        lambda x: ""
        if x in ("nan", "nan%", "NAN")
        and current_app.config.get("FLEXMEASURES_HIDE_NAN_IN_UI", False)
        else x
    )
    app.jinja_env.filters["asset_icon"] = asset_icon_name
    app.jinja_env.filters["username"] = username


def add_jinja_variables(app):
    # Set variables for Jinja template context
    for v in (
        "FLEXMEASURES_MODE",
        "FLEXMEASURES_PLATFORM_NAME",
        "FLEXMEASURES_SHOW_CONTROL_UI",
        "FLEXMEASURES_PUBLIC_DEMO_CREDENTIALS",
    ):
        app.jinja_env.globals[v] = app.config.get(v, "")
    app.jinja_env.globals["documentation_exists"] = (
        True
        if os.path.exists(
            "%s/static/documentation/html/index.html" % flexmeasures_ui.root_path
        )
        else False
    )
