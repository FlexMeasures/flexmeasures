from flask import Flask, Blueprint

from flexmeasures.api.v2_0.implementations.sensor_data import SensorDataAPI

flexmeasures_api = Blueprint("flexmeasures_api_v2_0", __name__)


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    import flexmeasures.api.v2_0.routes  # noqa: F401 this is necessary to load the endpoints

    v2_0_api_prefix = "/api/v2_0"

    app.register_blueprint(flexmeasures_api, url_prefix=v2_0_api_prefix)

    SensorDataAPI.register(app, route_prefix=v2_0_api_prefix)
