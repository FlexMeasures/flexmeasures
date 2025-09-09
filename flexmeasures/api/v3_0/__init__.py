"""
FlexMeasures API v3
"""

from flask import Flask
import json

from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin
from apispec_webframeworks.flask import FlaskPlugin
from flask_swagger_ui import get_swaggerui_blueprint

from flexmeasures.api.v3_0.sensors import SensorAPI
from flexmeasures.api.v3_0.accounts import AccountAPI
from flexmeasures.api.v3_0.users import UserAPI
from flexmeasures.api.v3_0.assets import AssetAPI, AssetTypesAPI
from flexmeasures.api.v3_0.health import HealthAPI
from flexmeasures.api.v3_0.public import ServicesAPI


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    v3_0_api_prefix = "/api/v3_0"

    SensorAPI.register(app, route_prefix=v3_0_api_prefix)
    AccountAPI.register(app, route_prefix=v3_0_api_prefix)
    UserAPI.register(app, route_prefix=v3_0_api_prefix)
    AssetAPI.register(app, route_prefix=v3_0_api_prefix)
    AssetTypesAPI.register(app, route_prefix=v3_0_api_prefix)
    HealthAPI.register(app, route_prefix=v3_0_api_prefix)
    ServicesAPI.register(app)

    register_swagger_ui(app)


def create_openapi_specs(app: Flask):
    """ """
    spec = APISpec(
        title="FlexMeasures",
        version="0.28.0",  # TODO: dynamic
        openapi_version="3.0.2",  # TODO: newest is 3.1.0
        plugins=[FlaskPlugin(), MarshmallowPlugin()],
    )
    api_key_scheme = {
        "type": "apiKey",
        "in": "header",
        "name": "Authorization",
    }  # TODO: should we stop making this configurable?
    spec.components.security_scheme("ApiKeyAuth", api_key_scheme)

    with app.test_request_context():
        for resource_name in ["SensorAPI"]:  # TODO: list others
            # endpoints:dict = [{ep_name: ep} for ep, ep_name in app.view_functions if ep_name.starts_with(resource_name)]
            # print(endpoints)
            spec.path(
                view=app.view_functions["SensorAPI:fetch_one"]
            )  # TODO: get all views from the registered routes

    spec_out = json.dumps(spec.to_dict(), indent=2)
    print(spec_out)


def register_swagger_ui(app: Flask):
    """
    Register the Swagger UI blueprint to view the OpenAPI specs.
    """
    SWAGGER_URL = "/api/docs"  # URL for exposing Swagger UI (without trailing '/')
    API_URL = "/ui/static/openapi-specs.json"

    # Call factory function to create our blueprint
    swaggerui_blueprint = get_swaggerui_blueprint(
        SWAGGER_URL,  # Swagger UI static files will be mapped to '{SWAGGER_URL}/dist/'
        API_URL,
        config={"app_name": "FlexMeasures"},  # Swagger UI config overrides
        # oauth_config={  # OAuth config. See https://github.com/swagger-api/swagger-ui#oauth2-configuration .
        #    'clientId': "your-client-id",
        #    'clientSecret': "your-client-secret-if-required",
        #    'realm': "your-realms",
        #    'appName': "your-app-name",
        #    'scopeSeparator': " ",
        #    'additionalQueryStringParams': {'test': "hello"}
        # }
    )

    app.register_blueprint(swaggerui_blueprint)
