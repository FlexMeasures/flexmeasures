from flask import Flask, Blueprint

from flexmeasures.api.v3_0.implementations.sensor_data import SensorDataAPI
from flexmeasures.api.v3_0.implementations.users import UserAPI


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    v3_0_api_prefix = "/api/v3_0"

    SensorDataAPI.register(app, route_prefix=v3_0_api_prefix)
    UserAPI.register(app, route_prefix=v3_0_api_prefix)
