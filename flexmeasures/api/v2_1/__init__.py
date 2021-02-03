from flask import Flask, Blueprint
from flask_smorest import Api, Blueprint, abort


flexmeasures_api_v2_1 = Blueprint("flexmeasures_api_v2_1", __name__, url_prefix="/api/v2_1")


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    #import flexmeasures.api.v2_1.routes  # noqa: F401 this is necessary to load the endpoints

    app.config['API_TITLE'] = 'My API'
    app.config['API_VERSION'] = 'v1'
    app.config['OPENAPI_VERSION'] = '3.0.2'
    api = Api(app)
    from flexmeasures.api.v2_1.implementations.users import Users
    api.register_blueprint(flexmeasures_api_v2_1)
