from flask import Flask

from flexmeasures.api.v3_0.sensors import SensorAPI
from flexmeasures.api.v3_0.users import UserAPI
from flexmeasures.api.v3_0.assets import AssetAPI
from flexmeasures.api.v3_0.health import HealthAPI


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    v3_0_api_prefix = "/api/v3_0"

    apis = (SensorAPI, UserAPI, AssetAPI, HealthAPI)

    for api_cls in apis:
        if hasattr(api_cls, "_rate_limiter"):
            # function will return a flask-rate limit defined by this API
            api_cls.decorators.append(api_cls._rate_limiter(app))
        api_cls.register(app, route_prefix=v3_0_api_prefix)
