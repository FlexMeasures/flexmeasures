from flask import Flask, Blueprint
from flask import send_from_directory
from flask_security import login_required, roles_accepted
from inflection import humanize, parameterize
import rq_dashboard

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
    @roles_accepted("admin")
    def basic_auth():
        """Ensure basic authorization."""
        return

    rq_dashboard.blueprint.before_request(basic_auth)
    app.register_blueprint(rq_dashboard.blueprint, url_prefix="/rq")


def add_jinja_filters(app):
    app.jinja_env.filters["zip"] = zip  # Allow zip function in templates
    app.jinja_env.add_extension(
        "jinja2.ext.do"
    )  # Allow expression statements (e.g. for modifying lists)
    app.jinja_env.filters["localized_datetime"] = localized_datetime_str
    app.jinja_env.filters["naturalized_datetime"] = naturalized_datetime_str
    app.jinja_env.filters["humanize"] = humanize
    app.jinja_env.filters["parameterize"] = parameterize
