"""
FlexMeasures API v3
"""

from pathlib import Path

from flask import Flask
import json

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
    """
    Create OpenAPI specs for the API and save them to a JSON file in the static folder.
    This function should be called when generating docs (and needs extra dependencies).
    """
    from apispec import APISpec
    from apispec.ext.marshmallow import MarshmallowPlugin
    from apispec_webframeworks.flask import FlaskPlugin

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

    # Explicitly register OpenAPI-compatible schemas
    schemas = [
        ("FlexContextOpenAPISchema", flex_context_schema_openAPI),
        ("UserAPIQuerySchema", UserAPIQuerySchema),
        ("AssetAPIQuerySchema", AssetAPIQuerySchema),
        ("AssetSchema", AssetSchema),
        ("DefaultAssetViewJSONSchema", DefaultAssetViewJSONSchema),
        ("AccountSchema", AccountSchema(partial=True)),
        ("AccountAPIQuerySchema", AccountAPIQuerySchema),
        ("AuthRequestSchema", AuthRequestSchema),
    ]

    for name, schema in schemas:
        spec.components.schema(name, schema=schema)

    with app.test_request_context():
        documented_endpoints_counter = 0

        for rule in app.url_map.iter_rules():
            endpoint_name = rule.endpoint
            if endpoint_name not in app.view_functions:
                continue

            view_function = app.view_functions[endpoint_name]

            # Document all API endpoints under /api or root /
            if rule.rule.startswith("/api/") or rule.rule == "/":
                try:
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
