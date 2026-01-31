"""
FlexMeasures API v3
"""

from pathlib import Path
from typing import Any, Type

from flask import Flask
import json

from apispec import APISpec
from apispec_oneofschema import MarshmallowPlugin
from apispec_webframeworks.flask import FlaskPlugin
from flask_swagger_ui import get_swaggerui_blueprint
from marshmallow import Schema

from flexmeasures import __version__ as fm_version
from flexmeasures.api.v3_0.sensors import SensorAPI
from flexmeasures.api.v3_0.accounts import AccountAPI
from flexmeasures.api.v3_0.users import UserAPI
from flexmeasures.api.v3_0.assets import AssetAPI, AssetTypesAPI
from flexmeasures.api.v3_0.sources import DataSourcesAPI
from flexmeasures.api.v3_0.health import HealthAPI
from flexmeasures.api.v3_0.public import ServicesAPI
from flexmeasures.api.v3_0.deprecated import SensorEntityAddressAPI
from flexmeasures.api.v3_0.assets import (
    flex_context_schema_openAPI,
    AssetAPIQuerySchema,
    DefaultAssetViewJSONSchema,
)
from flexmeasures.data.schemas.generic_assets import GenericAssetSchema as AssetSchema
from flexmeasures.data.schemas.sensors import QuantitySchema, TimeSeriesSchema
from flexmeasures.data.schemas.sources import DataSourcesSchema
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
    DataSourcesAPI.register(app, route_prefix=v3_0_api_prefix)
    HealthAPI.register(app, route_prefix=v3_0_api_prefix)
    ServicesAPI.register(app)
    SensorEntityAddressAPI.register(app, route_prefix=v3_0_api_prefix)

    register_swagger_ui(app)


def collapse_schema_to_field(
    spec: APISpec,
    schema_cls: Type[Schema],
    field_name: str,
) -> dict[str, Any]:
    """
    Replace the OpenAPI component named after `schema_cls` with the
    OpenAPI schema generated for `field_name` inside that schema.
    """
    # 1. Find the Marshmallow plugin
    try:
        ma_plugin = next(p for p in spec.plugins if isinstance(p, MarshmallowPlugin))
    except StopIteration:
        raise RuntimeError("No MarshmallowPlugin found in spec.")

    # 2. Get the field from the schema class
    field = schema_cls._declared_fields[field_name]

    # 3. Convert it to an OpenAPI schema object
    field_schema = ma_plugin.converter.field2property(field)

    # 4. Replace the component schema
    component_name = schema_cls.__name__.replace("Schema", "")
    spec.components.schemas[component_name] = field_schema

    return field_schema


def create_openapi_specs(app: Flask):
    """
    Create OpenAPI specs for the API and save them to a JSON file in the static folder.
    This function should be called when generating docs (and needs extra dependencies).
    """
    version = ".".join(
        fm_version.split(".")[:3]
    )  # only keep major, minor and patch parts
    platform_name = app.config.get("FLEXMEASURES_PLATFORM_NAME", "FlexMeasures")
    token_header_name = app.config.get("SECURITY_TOKEN_AUTHENTICATION_HEADER")

    api_intro = (
        f"Welcome to the {platform_name} API."
        "<br/>"
        'This is a platform for smart energy scheduling (a "Cloud EMS"). '
        "<br/><br/>"
        "To use the API, you need to be authenticated."
        "<br/>"
        "If you are currently logged in to the platform, you can try out all endpoints on this page right away!"
        "<br/>"
        'You can alternatively add a token via the "Authorize" button on the right. You can find an API access token on <a href="/logged-in-user">your user page</a> - or ask the host.'
    )
    if app.config.get("FLEXMEASURES_SIGNUP_PAGE", None):
        api_intro += f'<br/>No account yet? <a href="{app.config.get("FLEXMEASURES_SIGNUP_PAGE")}">Sign up here</a>.<br/>'
    api_intro += (
        "<br/>"
        f"If you write code against these API endpoints, then include an `{token_header_name}` header in your requests with the API token. "
        'If you use Python, check out the <a href="https://github.com/FlexMeasures/flexmeasures-client" target="_blank">Python client</a>.'
    )

    spec = APISpec(
        title="FlexMeasures",
        version=version,
        info=dict(
            description=api_intro,
            contact={
                "name": f"{platform_name} Support",
                "url": app.config.get("FLEXMEASURES_SUPPORT_PAGE"),
            },
            termsOfService=app.config.get("FLEXMEASURES_TOS_PAGE"),
        ),
        openapi_version=app.config["OPENAPI_VERSION"],
        externalDocs=dict(
            description=f"{platform_name} runs on the open source FlexMeasures technology. Read the docs here.",
            url="https://flexmeasures.readthedocs.io",
        ),
        plugins=[FlaskPlugin(), MarshmallowPlugin()],
    )
    api_key_scheme = {
        "type": "apiKey",
        "in": "header",
        "name": token_header_name,
    }  # TODO: should we stop making this a configurable parameter, as the client cannot read this setting? Or configure the client accordingly?
    spec.components.security_scheme("ApiKeyAuth", api_key_scheme)

    # Explicitly register OpenAPI-compatible schemas
    schemas = [
        ("FlexContextOpenAPISchema", flex_context_schema_openAPI),
        ("UserAPIQuerySchema", UserAPIQuerySchema),
        ("AssetAPIQuerySchema", AssetAPIQuerySchema),
        ("AssetSchema", AssetSchema),
        ("DataSourcesSchema", DataSourcesSchema),
        ("DefaultAssetViewJSONSchema", DefaultAssetViewJSONSchema),
        ("AccountSchema", AccountSchema(partial=True)),
        ("AccountAPIQuerySchema", AccountAPIQuerySchema),
        ("AuthRequestSchema", AuthRequestSchema),
    ]

    for name, schema in schemas:
        spec.components.schema(name, schema=schema)

    last_exception = None
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
                    last_exception = e

    # Collapse Quantity and TimeSeries schemas to fields
    collapse_schema_to_field(spec, QuantitySchema, "quantity")
    collapse_schema_to_field(spec, TimeSeriesSchema, "timeseries")

    output_path = Path("flexmeasures/ui/static/openapi-specs.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(spec.to_dict(), f, indent=2)

    print(f"✅ Documented {documented_endpoints_counter} endpoints to {output_path}")
    if last_exception:
        # Reraise last exception
        raise last_exception


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
