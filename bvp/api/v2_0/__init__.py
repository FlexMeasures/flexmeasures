from flask import Flask, Blueprint

bvp_api = Blueprint("bvp_api_v2_0", __name__)


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    import bvp.api.v2_0.routes  # noqa: F401 this is necessary to load the endpoints

    app.register_blueprint(bvp_api, url_prefix="/api/v2_0")
