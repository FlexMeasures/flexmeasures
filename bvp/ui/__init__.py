import os

from flask import current_app, Flask, Blueprint
from flask import send_from_directory
from flask_security import login_required, roles_accepted
import numpy as np
import rq_dashboard
from humanize import naturaldelta

from bvp.utils.bvp_inflection import (
    capitalize,
    parameterize,
)
from bvp.utils.time_utils import localized_datetime_str, naturalized_datetime_str


# The ui blueprint. It is registered with the Flask app (see app.py)
bvp_ui = Blueprint(
    "bvp_ui",
    __name__,
    static_folder="static",
    static_url_path="/ui/static",
    template_folder="templates",
)


def register_at(app: Flask):
    """This can be used to register this blueprint together with other ui-related things"""

    from bvp.ui.crud.assets import AssetCrud
    from bvp.ui.crud.users import UserCrud

    AssetCrud.register(app)
    UserCrud.register(app)

    import bvp.ui.views  # noqa: F401 this is necessary to load the views

    app.register_blueprint(
        bvp_ui
    )  # now registering the blueprint will affect all views

    register_rq_dashboard(app)

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            bvp_ui.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon"
        )

    from bvp.ui.error_handlers import add_html_error_views

    add_html_error_views(app)
    add_jinja_filters(app)
    add_jinja_variables(app)


def register_rq_dashboard(app):
    app.config.update(
        RQ_DASHBOARD_REDIS_URL=[
            "redis://:%s@%s:%s/%s"
            % (
                app.config.get("BVP_REDIS_PASSWORD", ""),
                app.config.get("BVP_REDIS_URL", ""),
                app.config.get("BVP_REDIS_PORT", ""),
                app.config.get("BVP_REDIS_DB_NR", ""),
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
    if app.config.get("BVP_MODE", "") == "demo":
        rq_dashboard.blueprint.before_request(basic_auth)
    else:
        rq_dashboard.blueprint.before_request(basic_admin_auth)

    # Todo: rq dashboard has no way of passing BVP template variables, so how to conditionally disable menu items?
    app.register_blueprint(rq_dashboard.blueprint, url_prefix="/tasks")


def add_jinja_filters(app):
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
        and current_app.config.get("BVP_HIDE_NAN_IN_UI", False)
        else x
    )


def add_jinja_variables(app):
    # Set variables for Jinja template context
    for v in ("BVP_MODE", "BVP_PUBLIC_DEMO"):
        app.jinja_env.globals[v] = app.config.get(v, "")
    app.jinja_env.globals["documentation_exists"] = (
        True
        if os.path.exists("%s/static/documentation/html/index.html" % bvp_ui.root_path)
        else False
    )
