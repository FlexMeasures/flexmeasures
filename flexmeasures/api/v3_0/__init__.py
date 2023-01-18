from flask import Flask, request
from flask_security import current_user

from flexmeasures.api.v3_0.sensors import SensorAPI
from flexmeasures.api.v3_0.users import UserAPI
from flexmeasures.api.v3_0.assets import AssetAPI
from flexmeasures.api.v3_0.health import HealthAPI


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    v3_0_api_prefix = "/api/v3_0"

    def cost_function() -> int:
        if request.endpoint == "SensorAPI:trigger_schedule":
            return 1
        return 0

    # Apply rate limit: a schedule can be triggered once per 5 minutes per sensor per account
    SensorAPI.decorators.append(app.limiter.limit("1 per 5 minutes", key_func=lambda: str(current_user.account_id) + request.view_args.get("id", ""), cost=cost_function))

    SensorAPI.register(app, route_prefix=v3_0_api_prefix)
    UserAPI.register(app, route_prefix=v3_0_api_prefix)
    AssetAPI.register(app, route_prefix=v3_0_api_prefix)
    HealthAPI.register(app, route_prefix=v3_0_api_prefix)
