from flask import Flask, Blueprint

from flask import send_from_directory

from bvp.utils.time_utils import localized_datetime_str, naturalized_datetime_str
from bvp.data import auth_setup


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
    import bvp.ui.views.error_views  # noqa: F401 this is necessary to load the views

    app.register_blueprint(
        bvp_ui
    )  # now registering the blueprint will affect all views

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            bvp_ui.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon"
        )

    from bvp.ui.utils.view_utils import render_bvp_template

    def unauth_handler():
        """An unauth handler which renders an HTML error page"""
        return (
            render_bvp_template(
                "error.html",
                error_class=auth_setup.UNAUTH_ERROR_CLASS,
                error_message=auth_setup.UNAUTH_MSG,
            ),
            auth_setup.UNAUTH_STATUS_CODE,
        )

    app.unauth_handler_html = unauth_handler

    app.jinja_env.filters["zip"] = zip  # Allow zip function in templates
    app.jinja_env.add_extension(
        "jinja2.ext.do"
    )  # Allow expression statements (e.g. for modifying lists)
    app.jinja_env.filters["localized_datetime"] = localized_datetime_str
    app.jinja_env.filters["naturalized_datetime"] = naturalized_datetime_str
