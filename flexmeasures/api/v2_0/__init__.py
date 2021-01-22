from flask import Flask, Blueprint

flexmeasures_api = Blueprint("flexmeasures_api_v2_0", __name__)


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    import flexmeasures.api.v2_0.routes  # noqa: F401 this is necessary to load the endpoints

    app.register_blueprint(flexmeasures_api, url_prefix="/api/v2_0")
