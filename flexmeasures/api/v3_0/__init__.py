"""
FlexMeasures API v3
"""

from pathlib import Path

from flask import Flask
import json

from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin
from apispec_webframeworks.flask import FlaskPlugin
from flask_swagger_ui import get_swaggerui_blueprint

from flexmeasures import __version__ as fm_version
from flexmeasures.api.v3_0.sensors import SensorAPI
from flexmeasures.api.v3_0.accounts import AccountAPI
from flexmeasures.api.v3_0.users import UserAPI
from flexmeasures.api.v3_0.assets import AssetAPI, AssetTypesAPI
from flexmeasures.api.v3_0.health import HealthAPI
from flexmeasures.api.v3_0.public import ServicesAPI
from flexmeasures.api.v3_0.deprecated import SensorEntityAddressAPI
from flexmeasures.api.v3_0.assets import (
    flex_context_schema_openAPI,
    AssetAPIQuerySchema,
    DefaultAssetViewJSONSchema,
)
from flexmeasures.data.schemas.generic_assets import GenericAssetSchema as AssetSchema
from flexmeasures.data.schemas.account import AccountSchema
from flexmeasures.api.v3_0.accounts import AccountAPIQuerySchema
from flexmeasures.api.v3_0.users import UserAPIQuerySchema, AuthRequestSchema


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
    SensorEntityAddressAPI.register(app, route_prefix=v3_0_api_prefix)

    register_swagger_ui(app)


def create_openapi_specs(app: Flask):
    """ """
    spec = APISpec(
        title="FlexMeasures",
        version=fm_version,
        openapi_version="3.0.2",  # TODO: newest is 3.1.0
        plugins=[FlaskPlugin(), MarshmallowPlugin()],
    )
    api_key_scheme = {
        "type": "apiKey",
        "in": "header",
        "name": "Authorization",
    }  # TODO: should we stop making this a configurable parameter?
    spec.components.security_scheme("ApiKeyAuth", api_key_scheme)

    # explicitly register OpenAPI-compatible schemas
    spec.components.schema(
        "FlexContextOpenAPISchema", schema=flex_context_schema_openAPI
    )
    spec.components.schema("UserAPIQuerySchema", schema=UserAPIQuerySchema)
    spec.components.schema("AssetAPIQuerySchema", schema=AssetAPIQuerySchema)
    spec.components.schema("AssetSchema", schema=AssetSchema)
    spec.components.schema(
        "DefaultAssetViewJSONSchema", schema=DefaultAssetViewJSONSchema
    )
    spec.components.schema("AccountSchema", schema=AccountSchema(partial=True))
    spec.components.schema("AccountAPIQuerySchema", schema=AccountAPIQuerySchema)
    spec.components.schema("AuthRequestSchema", schema=AuthRequestSchema)

    with app.test_request_context():
        documented_endpoints_counter = 0
        # Document ALL API endpoints under /api/v3_0/
        for rule in app.url_map.iter_rules():
            if rule.rule.startswith("/api/v3_0/"):
                endpoint_name = rule.endpoint
                if endpoint_name in app.view_functions:
                    try:
                        view_function = app.view_functions[endpoint_name]
                        spec.path(view=view_function)
                        documented_endpoints_counter += 1
                    except Exception as e:
                        print(f"❌ Failed to document {rule.rule}: {e}")
            # Document API endpoint /api/requestAuthToken
            if rule.rule == "/api/requestAuthToken":
                endpoint_name = rule.endpoint
                if endpoint_name in app.view_functions:
                    try:
                        view_function = app.view_functions[endpoint_name]
                        spec.path(view=view_function)
                        documented_endpoints_counter += 1
                    except Exception as e:
                        print(f"❌ Failed to document {rule.rule}: {e}")

    output_path = Path("flexmeasures/ui/static/openapi-specs.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(spec.to_dict(), f, indent=2)

    print(f"✅ Documented {documented_endpoints_counter} endpoints to {output_path}")


def register_swagger_ui(app: Flask):
    """
    Register the Swagger UI blueprint to view the OpenAPI specs.
    """
    SWAGGER_URL = "/api/v3_0/docs"  # URL for exposing Swagger UI (without trailing '/')
    API_URL = "/ui/static/openapi-specs.json"

    # Call factory function to create our blueprint
    swaggerui_blueprint = get_swaggerui_blueprint(
        SWAGGER_URL,  # Swagger UI static files will be mapped to '{SWAGGER_URL}/dist/'
        API_URL,
        config={
            "app_name": "FlexMeasures",
            "layout": "BaseLayout",
        },  # Swagger UI config overrides
    )

    app.register_blueprint(swaggerui_blueprint)
