"""
FlexMeasures API v3
"""

from flask import Flask

from flexmeasures.api.v3_0.sensors import SensorAPI
from flexmeasures.api.v3_0.accounts import AccountAPI
from flexmeasures.api.v3_0.users import UserAPI
from flexmeasures.api.v3_0.assets import AssetAPI
from flexmeasures.api.v3_0.health import HealthAPI
from flexmeasures.api.v3_0.public import ServicesAPI


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    v3_0_api_prefix = "/api/v3_0"

    SensorAPI.register(app, route_prefix=v3_0_api_prefix)
    AccountAPI.register(app, route_prefix=v3_0_api_prefix)
    UserAPI.register(app, route_prefix=v3_0_api_prefix)
    AssetAPI.register(app, route_prefix=v3_0_api_prefix)
    HealthAPI.register(app, route_prefix=v3_0_api_prefix)
    ServicesAPI.register(app)
