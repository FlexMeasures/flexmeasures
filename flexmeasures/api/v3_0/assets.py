from __future__ import annotations
import json
from datetime import datetime, timedelta
from http import HTTPStatus
from humanize import naturaldelta

from flask import request
from flask_classful import FlaskView, route
from flask_login import current_user
from flask_security import auth_required
from flask_json import as_json
from flask_sqlalchemy.pagination import SelectPagination

from marshmallow import fields, ValidationError, Schema, validate

from webargs.flaskparser import use_kwargs, use_args
from sqlalchemy import select, func, or_

from flexmeasures.data.services.generic_assets import (
    create_asset,
    patch_asset,
    delete_asset,
)
from flexmeasures.data.services.sensors import (
    build_asset_jobs_data,
    get_sensor_stats,
)
from flexmeasures.api.common.schemas.utils import make_openapi_compatible
from flexmeasures.api.common.schemas.generic_schemas import PaginationSchema
from flexmeasures.api.common.schemas.assets import (
    AssetAPIQuerySchema,
    AssetPaginationSchema,
)
from flexmeasures.data.services.job_cache import NoRedisConfigured
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.queries.generic_assets import query_assets_by_search_terms
from flexmeasures.data.schemas import AwareDateTimeField
from flexmeasures.data.schemas.generic_assets import (
    GenericAssetSchema as AssetSchema,
    GenericAssetIdField as AssetIdField,
    GenericAssetTypeSchema as AssetTypeSchema,
)
from flexmeasures.data.schemas.scheduling.storage import StorageFlexModelSchema
from flexmeasures.data.schemas.scheduling import AssetTriggerSchema, FlexContextSchema
from flexmeasures.data.services.scheduling import (
    create_sequential_scheduling_job,
    create_simultaneous_scheduling_job,
)
from flexmeasures.api.common.utils.api_utils import get_accessible_accounts
from flexmeasures.api.common.responses import (
    invalid_flex_config,
    request_processed,
)
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.utils.coding_utils import (
    flatten_unique,
)
from flexmeasures.ui.utils.view_utils import clear_session, set_session_variables
from flexmeasures.auth.policy import check_access
from flexmeasures.data.schemas.sensors import (
    SensorSchema,
)
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.utils.time_utils import naturalized_datetime_str
from flexmeasures.data.utils import get_downsample_function_and_value

asset_type_schema = AssetTypeSchema()
asset_schema = AssetSchema()
assets_schema = AssetSchema(many=True)
patch_asset_schema = AssetSchema(partial=True, exclude=["account_id"])
sensor_schema = SensorSchema()
sensors_schema = SensorSchema(many=True)


# Create FlexContext, FlexModel and AssetTrigger OpenAPI compatible schemas
storage_flex_model_schema_openAPI = make_openapi_compatible(StorageFlexModelSchema)
flex_context_schema_openAPI = make_openapi_compatible(FlexContextSchema)


class AssetTriggerOpenAPISchema(AssetTriggerSchema):
    flex_context = fields.Nested(flex_context_schema_openAPI, required=True)
    flex_model = fields.Nested(storage_flex_model_schema_openAPI, required=True)


class AssetChartKwargsSchema(Schema):
    event_starts_after = AwareDateTimeField(format="iso", required=False)
    event_ends_before = AwareDateTimeField(format="iso", required=False)
    beliefs_after = AwareDateTimeField(format="iso", required=False)
    beliefs_before = AwareDateTimeField(format="iso", required=False)
    include_data = fields.Boolean(required=False)
    combine_legend = fields.Boolean(required=False, load_default=True)
    dataset_name = fields.Str(required=False)
    height = fields.Str(required=False)
    width = fields.Str(required=False)
    chart_type = fields.Str(required=False)


class AssetChartDataKwargsSchema(Schema):
    event_starts_after = AwareDateTimeField(format="iso", required=False)
    event_ends_before = AwareDateTimeField(format="iso", required=False)
    beliefs_after = AwareDateTimeField(format="iso", required=False)
    beliefs_before = AwareDateTimeField(format="iso", required=False)
    most_recent_beliefs_only = fields.Boolean(required=False)
    compress_json = fields.Boolean(required=False)


class AssetAuditLogPaginationSchema(PaginationSchema):
    sort_by = fields.Str(
        required=False,
        validate=validate.OneOf(["event_datetime"]),
    )


class DefaultAssetViewJSONSchema(Schema):
    default_asset_view = fields.Str(
        required=True,
        validate=validate.OneOf(
            ["Audit Log", "Context", "Graphs", "Properties", "Status"]
        ),
        metadata={
            "enum": ["Audit Log", "Context", "Graphs", "Properties", "Status"],
            "description": "The default asset view to show.",
        },
    )
    use_as_default = fields.Bool(
        required=False,
        load_default=True,
        metadata={"description": "Whether to use this view as default."},
    )


class KPIKwargsSchema(Schema):
    event_starts_after = AwareDateTimeField(format="iso", required=False)
    event_ends_before = AwareDateTimeField(format="iso", required=False)


class AssetTypesAPI(FlaskView):
    """
    This API view exposes generic asset types.
    """

    route_base = "/assets/types"
    trailing_slash = False
    decorators = [auth_required()]

    @route("", methods=["GET"])
    @as_json
    def index(self):
        """
        .. :quickref: Assets; Get list of available asset types
        ---
        get:
          summary: Get list of available asset types
          security:
            - ApiKeyAuth: []
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  examples:
                    single_asset_type:
                      summary: One asset type being returned in the response
                      value:
                        - id: 1
                          name: solar
                          description: solar panel(s)
          tags:
            - Assets
        """
        response = asset_type_schema.dump(
            db.session.scalars(select(GenericAssetType)).all(), many=True
        )
        return response, 200


class AssetAPI(FlaskView):
    """
    This API view exposes generic assets.
    """

    route_base = "/assets"
    trailing_slash = False
    decorators = [auth_required()]

    @route("", methods=["GET"])
    @use_kwargs(AssetAPIQuerySchema, location="query")
    @as_json
    def index(
        self,
        account: Account | None,
        all_accessible: bool,
        include_public: bool,
        page: int | None = None,
        per_page: int | None = None,
        filter: list[str] | None = None,
        sort_by: str | None = None,
        sort_dir: str | None = None,
    ):
        """
        .. :quickref: Assets; List all assets owned  by user's accounts, or a certain account or all accessible accounts.
        ---
        get:
          summary: List all assets owned  by user's accounts, or a certain account or all accessible accounts.
          description: |
            This endpoint returns all accessible assets by accounts.

              - The `account_id` query parameter can be used to list assets from any account (if the user is allowed to read them). Per default, the user's account is used.
              - Alternatively, the `all_accessible` query parameter can be used to list assets from all accounts the current_user has read-access to, plus all public assets. Defaults to `false`.
              - The `include_public` query parameter can be used to include public assets in the response. Defaults to `false`.

            The endpoint supports pagination of the asset list using the `page` and `per_page` query parameters.
              - If the `page` parameter is not provided, all assets are returned, without pagination information. The result will be a list of assets.
              - If a `page` parameter is provided, the response will be paginated, showing a specific number of assets per page as defined by `per_page` (default is 10).
              - If a search 'filter' such as 'solar "ACME corp"' is provided, the response will filter out assets where each search term is either present in their name or account name.
              The response schema for pagination is inspired by [DataTables](https://datatables.net/manual/server-side#Returned-data)

          security:
            - ApiKeyAuth: []
          parameters:
            - in: query
              schema: AssetAPIQuerySchema
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  examples:
                    single_asset:
                      summary: One asset being returned in the response
                      value:
                        data:
                        - id: 1
                          name: Test battery
                          latitude: 10
                          longitude: 100
                          account_id: 2
                          generic_asset_type:
                            id: 1
                            name: battery
                    paginated_assets:
                      summary: A paginated list of assets being returned in the response
                      value:
                        data:
                        - id: 1
                          name: Test battery
                          latitude: 10
                          longitude: 100
                          account_id: 2
                          generic_asset_type:
                            id: 1
                            name: battery
                        num-records: 1
                        filtered-records: 1
            400:
              description: INVALID_REQUEST
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Assets
        """

        # find out which accounts are relevant
        if all_accessible:
            accounts = get_accessible_accounts()
        else:
            if account is None:
                account = current_user.account
            check_access(account, "read")
            accounts = [account]

        filter_statement = GenericAsset.account_id.in_([a.id for a in accounts])

        # add public assets if the request asks for all the accessible assets
        if all_accessible or include_public:
            filter_statement = filter_statement | GenericAsset.account_id.is_(None)

        query = query_assets_by_search_terms(
            search_terms=filter,
            filter_statement=filter_statement,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

        if page is None:
            response = asset_schema.dump(db.session.scalars(query).all(), many=True)
        else:
            if per_page is None:
                per_page = 10

            select_pagination: SelectPagination = db.paginate(
                query, per_page=per_page, page=page
            )
            num_records = db.session.scalar(
                select(func.count(GenericAsset.id)).filter(filter_statement)
            )
            response = {
                "data": asset_schema.dump(select_pagination.items, many=True),
                "num-records": num_records,
                "filtered-records": select_pagination.total,
            }

        return response, 200

    @route(
        "/<id>/sensors",
        methods=["GET"],
    )
    @use_kwargs(
        {
            "asset": AssetIdField(data_key="id"),
        },
        location="path",
    )
    @use_kwargs(AssetPaginationSchema, location="query")
    @as_json
    def asset_sensors(
        self,
        id: int,
        asset: GenericAsset | None,
        page: int | None = None,
        per_page: int | None = None,
        filter: list[str] | None = None,
        sort_by: str | None = None,
        sort_dir: str | None = None,
    ):
        """
        .. :quickref: Assets; Return all sensors under an asset.
        ---
        get:
          summary: Return all sensors under an asset.
          description: |
            This endpoint returns all sensors under an asset.

            The endpoint supports pagination of the asset list using the `page` and `per_page` query parameters.

            - If the `page` parameter is not provided, all sensors are returned, without pagination information. The result will be a list of sensors.
            - If a `page` parameter is provided, the response will be paginated, showing a specific number of assets per page as defined by `per_page` (default is 10).
            The response schema for pagination is inspired by https://datatables.net/manual/server-side#Returned-data
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              description: ID of the asset to fetch sensors for
              schema:
                type: integer
            - in: query
              schema: AssetPaginationSchema
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  examples:
                    single_asset:
                      summary: One asset being returned in the response
                      value:
                        data:
                        - id: 1
                          name: Test battery
                          latitude: 10
                          longitude: 100
                          account_id: 2
                          generic_asset_type:
                            id: 1
                            name: battery
                    paginated_assets:
                      summary: A paginated list of assets being returned in the response
                      value:
                        data:
                        - id: 1
                          name: Test battery
                          latitude: 10
                          longitude: 100
                          account_id: 2
                          generic_asset_type:
                            id: 1
                            name: battery
                        num-records: 1
                        filtered-records: 1
            400:
              description: INVALID_REQUEST
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Assets
        """
        query_statement = Sensor.generic_asset_id == asset.id

        query = select(Sensor).filter(query_statement)

        if filter:
            search_terms = filter[0].split(" ")
            query = query.filter(
                or_(*[Sensor.name.ilike(f"%{term}%") for term in search_terms])
            )

        if sort_by is not None and sort_dir is not None:
            valid_sort_columns = {
                "id": Sensor.id,
                "name": Sensor.name,
                "resolution": Sensor.event_resolution,
            }

            query = query.order_by(
                valid_sort_columns[sort_by].asc()
                if sort_dir == "asc"
                else valid_sort_columns[sort_by].desc()
            )

        select_pagination: SelectPagination = db.paginate(
            query, per_page=per_page, page=page
        )

        num_records = db.session.scalar(
            select(func.count(Sensor.id)).where(query_statement)
        )

        sensors_response: list = [
            {
                **sensor_schema.dump(sensor),
                "event_resolution": naturaldelta(sensor.event_resolution),
            }
            for sensor in select_pagination.items
        ]

        response = {
            "data": sensors_response,
            "num-records": num_records,
            "filtered-records": select_pagination.total,
        }

        return response, 200

    @route("/public", methods=["GET"])
    @as_json
    def public(self):
        """
        .. :quickref: Assets; Return all public assets.
        ---
        get:
          summary: Return all public assets.
          description: This endpoint returns all public assets.
          security:
            - ApiKeyAuth: []
          responses:
            200:
              description: PROCESSED
            400:
              description: INVALID_REQUEST
            401:
              description: UNAUTHORIZED
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Assets
        """
        assets = db.session.scalars(
            select(GenericAsset).filter(GenericAsset.account_id.is_(None))
        ).all()
        return assets_schema.dump(assets), 200

    @route("", methods=["POST"])
    @permission_required_for_context(
        "create-children", ctx_loader=AccountIdField.load_current
    )
    @use_args(asset_schema)
    def post(self, asset_data: dict):
        """
        .. :quickref: Assets; Creates a new asset.
        ---
        post:
          summary: Creates a new asset.
          description: |
            This endpoint creates a new asset.

            To establish a hierarchical relationship, you can optionally include the **parent_asset_id** in the request body to make the new asset a child of an existing asset.

          security:
            - ApiKeyAuth: []
          requestBody:
            content:
              application/json:
                schema: AssetSchema
                examples:
                  single_asset:
                    summary: Request to create a standalone asset
                    value:
                      name: Test battery
                      generic_asset_type_id: 2
                      account_id: 2
                      latitude: 40
                      longitude: 170.3
                  child_asset:
                    summary: Request to create an asset with a parent
                    value:
                      name: Test battery
                      generic_asset_type_id: 2
                      account_id: 2
                      parent_asset_id: 10
                      latitude: 40
                      longitude: 170.3
          responses:
            201:
              description: PROCESSED
              content:
                application/json:
                  examples:
                    single_asset:
                      summary: One asset being returned in the response
                      value:
                        generic_asset_type_id: 2
                        name: Test battery
                        id: 1
                        latitude: 10
                        longitude: 100
                        account_id: 1
                    child_asset:
                      summary: A child asset being returned in the response
                      value:
                        generic_asset_type_id: 2
                        name: Test battery
                        id: 1
                        latitude: 10
                        longitude: 100
                        account_id: 1
            400:
              description: INVALID_REQUEST
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Assets
        """
        asset = create_asset(asset_data)
        db.session.commit()

        return asset_schema.dump(asset), 201

    @route("/<id>", methods=["GET"])
    @use_kwargs(
        {
            "asset": AssetIdField(
                data_key="id", status_if_not_found=HTTPStatus.NOT_FOUND
            )
        },
        location="path",
    )
    @permission_required_for_context("read", ctx_arg_name="asset")
    @as_json
    def fetch_one(self, id, asset):
        """
        .. :quickref: Assets; Fetch a given asset.
        ---
        get:
          summary: Fetch a given asset.
          description: This endpoint gets an asset.
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              description: ID of the asset to fetch.
              schema:
                type: integer
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  examples:
                    single_asset:
                      summary: One asset being returned in the response
                      value:
                        generic_asset_type_id: 2
                        name: Test battery
                        id: 1
                        latitude: 10
                        longitude: 100
                        account_id: 1
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Assets
        """
        return asset_schema.dump(asset), 200

    @route("/<id>", methods=["PATCH"])
    @use_args(patch_asset_schema)
    @use_kwargs(
        {
            "db_asset": AssetIdField(
                data_key="id", status_if_not_found=HTTPStatus.NOT_FOUND
            )
        },
        location="path",
    )
    @permission_required_for_context("update", ctx_arg_name="db_asset")
    @as_json
    def patch(self, asset_data: dict, id: int, db_asset: GenericAsset):
        """
        .. :quickref: Assets; Update an asset given its identifier.
        ---
        patch:
          summary: Update an asset given its identifier.
          description: |
            This endpoint sets data for an existing asset.
            Any subset of asset fields can be sent.

            The following fields are not allowed to be updated:
            - id
            - account_id
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              description: ID of the asset to update.
              schema:
                type: integer
          requestBody:
            content:
              application/json:
                schema: AssetSchema
                examples:
                  single_asset:
                    summary: One asset being updated
                    value:
                      latitude: 11.1
                      longitude: 99.9
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  examples:
                    single_asset:
                      summary: the whole asset is returned in the response
                      value:
                        generic_asset_type_id: 2
                        name: Test battery
                        id: 1
                        latitude: 11.1
                        longitude: 99.9
                        account_id: 1
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Assets
        """
        try:
            db_asset = patch_asset(db_asset, asset_data)
        except ValidationError as e:
            return invalid_flex_config(str(e.messages))
        db.session.add(db_asset)
        db.session.commit()
        return asset_schema.dump(db_asset), 200

    @route("/<id>", methods=["DELETE"])
    @use_kwargs(
        {
            "asset": AssetIdField(
                data_key="id", status_if_not_found=HTTPStatus.NOT_FOUND
            )
        },
        location="path",
    )
    @permission_required_for_context("delete", ctx_arg_name="asset")
    @as_json
    def delete(self, id: int, asset: GenericAsset):
        """
        .. :quickref: Assets; Delete an asset.
        ---
        delete:
          summary: Delete an asset.
          description: This endpoint deletes an existing asset, as well as all sensors and measurements recorded for it.
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              description: ID of the asset to delete.
              schema:
                type: integer
          responses:
            204:
              description: DELETED
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Assets
        """
        delete_asset(asset)
        db.session.commit()
        return {}, 204

    @route("/<id>/chart", strict_slashes=False)  # strict on next version? see #1014
    @use_kwargs(
        {
            "asset": AssetIdField(
                data_key="id", status_if_not_found=HTTPStatus.NOT_FOUND
            )
        },
        location="path",
    )
    @use_kwargs(AssetChartKwargsSchema, location="query")
    @permission_required_for_context("read", ctx_arg_name="asset")
    def get_chart(self, id: int, asset: GenericAsset, **kwargs):
        """
        .. :quickref: Charts; Download an embeddable chart with time series data
        ---
        get:
          summary: Download an embeddable chart with time series data
          description: |
            This endpoint returns a chart with time series for an asset.

            The response contains the HTML and JavaScript needed to embedded and render the chart in an HTML page.
            This is used by the FlexMeasures UI.

            To learn how to embed the response in your web page, see [this section](https://flexmeasures.readthedocs.io/latest/tut/building_uis.html#embedding-charts) in the developer documentation.
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              description: ID of the asset to download a chart for.
              schema:
                type: integer
            - in: query
              schema: AssetChartKwargsSchema
          responses:
            200:
              description: PROCESSED
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Assets
        """
        # Store selected time range as session variables, for a consistent UX across UI page loads
        set_session_variables("event_starts_after", "event_ends_before")
        return json.dumps(asset.chart(**kwargs))

    @route(
        "/<id>/chart_data", strict_slashes=False
    )  # strict on next version? see #1014
    @use_kwargs(
        {
            "asset": AssetIdField(
                data_key="id", status_if_not_found=HTTPStatus.NOT_FOUND
            )
        },
        location="path",
    )
    @use_kwargs(
        {
            "event_starts_after": AwareDateTimeField(format="iso", required=False),
            "event_ends_before": AwareDateTimeField(format="iso", required=False),
            "beliefs_after": AwareDateTimeField(format="iso", required=False),
            "beliefs_before": AwareDateTimeField(format="iso", required=False),
            "most_recent_beliefs_only": fields.Boolean(required=False),
            "compress_json": fields.Boolean(required=False),
        },
        location="query",
    )
    @permission_required_for_context("read", ctx_arg_name="asset")
    def get_chart_data(self, id: int, asset: GenericAsset, **kwargs):
        """
        .. :quickref: Charts; Download time series for use in charts
        ---
        get:
          summary: Download time series for use in charts
          description: Data for use in charts (in case you have the chart specs already).
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              description: ID of the asset to download data for.
              schema:
                type: integer
            - in: query
              schema: AssetChartDataKwargsSchema
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  schema:
                    type: object
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Assets
        """
        sensors = flatten_unique(asset.validate_sensors_to_show())
        return asset.search_beliefs(sensors=sensors, as_json=True, **kwargs)

    @route("/<id>/auditlog")
    @use_kwargs(
        {"asset": AssetIdField(data_key="id")},
        location="path",
    )
    @permission_required_for_context("read", ctx_arg_name="asset")
    @use_kwargs(AssetAuditLogPaginationSchema, location="query")
    @as_json
    def auditlog(
        self,
        id: int,
        asset: GenericAsset,
        page: int | None = None,
        per_page: int | None = None,
        filter: list[str] | None = None,
        sort_by: str | None = None,
        sort_dir: str | None = None,
    ):
        """
        .. :quickref: Assets; Get history of asset related actions.
        ---
        get:
          summary: Get history of asset related actions.
          description: |
            The endpoint is paginated and supports search filters.
              - If the `page` parameter is not provided, all audit logs are returned paginated by `per_page` (default is 10).
              - If a `page` parameter is provided, the response will be paginated, showing a specific number of assets per page as defined by `per_page` (default is 10).
              - If `sort_by` (field name) and `sort_dir` ("asc" or "desc") are provided, the list will be sorted.
              - If a search 'filter' is provided, the response will filter out audit logs where each search term is either present in the event or active user name.
                The response schema for pagination is inspired by [DataTables](https://datatables.net/manual/server-side)
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              required: true
              description: ID of the asset to get the history for.
              schema:
                type: integer
            - in: query
              schema: AssetAuditLogPaginationSchema
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  schema:
                    type: object
                    examples:
                      pagination:
                        summary: Pagination response
                        value:
                          data:
                            - event: Asset test asset deleted
                              event_datetime: "2021-01-01T00:00:00"
                              active_user_name: 'Test user'
                          num_records: 1,
                          filtered_records: 1
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Assets
        """
        query_statement = AssetAuditLog.affected_asset_id == asset.id
        query = select(AssetAuditLog).filter(query_statement)

        if filter:
            search_terms = filter[0].split(" ")
            query = query.filter(
                or_(
                    *[AssetAuditLog.event.ilike(f"%{term}%") for term in search_terms],
                    *[
                        AssetAuditLog.active_user_name.ilike(f"%{term}%")
                        for term in search_terms
                    ],
                )
            )

        if sort_by is not None and sort_dir is not None:
            valid_sort_columns = {"event_datetime": AssetAuditLog.event_datetime}

            query = query.order_by(
                valid_sort_columns[sort_by].asc()
                if sort_dir == "asc"
                else valid_sort_columns[sort_by].desc()
            )

        select_pagination: SelectPagination = db.paginate(
            query, per_page=per_page, page=page
        )

        num_records = db.session.scalar(
            select(func.count(AssetAuditLog.id)).where(query_statement)
        )

        audit_logs_response: list = [
            {
                "event": audit_log.event,
                "event_datetime": naturalized_datetime_str(audit_log.event_datetime),
                "active_user_name": audit_log.active_user_name,
                "active_user_id": audit_log.active_user_id,
            }
            for audit_log in select_pagination.items
        ]

        response = {
            "data": audit_logs_response,
            "num-records": num_records,
            "filtered-records": select_pagination.total,
        }

        return response, 200

    @route("/<id>/jobs", methods=["GET"])
    @use_kwargs(
        {"asset": AssetIdField(data_key="id")},
        location="path",
    )
    @permission_required_for_context("read", ctx_arg_name="asset")
    @as_json
    def get_jobs(self, id: int, asset: GenericAsset):
        """
        .. :quickref: Assets; Get all background jobs related to an asset.
        ---
        get:
          summary: Get all background jobs related to an asset.
          description: |
            The response will be a list of jobs.
            Note that jobs in Redis have a limited TTL, so not all past jobs will be listed.
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              required: true
              description: ID of the asset to get the jobs for.
              schema:
                type: integer
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  examples:
                    jobs:
                      summary: List of jobs
                      value:
                        jobs:
                          -job_id: 1
                          queue: scheduling
                          asset_or_sensor_type: asset
                          asset_id: 1
                          status: finished
                          err: null
                          enqueued_at: "2023-10-01T00:00:00"
                          metadata_hash: abc123
                        redis_connection_err: null
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Assets
        """
        redis_connection_err = None
        all_jobs_data = list()
        try:
            jobs_data = build_asset_jobs_data(asset)
        except NoRedisConfigured as e:
            redis_connection_err = e.args[0]
        else:
            all_jobs_data = jobs_data

        return {
            "jobs": all_jobs_data,
            "redis_connection_err": redis_connection_err,
        }, 200

    @route("/default_asset_view", methods=["POST"])
    @as_json
    @use_kwargs(DefaultAssetViewJSONSchema, location="json")
    def update_default_asset_view(self, **kwargs):
        """
        .. :quickref: Assets; Update the default asset view for the current user
        ---
        post:
          summary: Update the default asset view for the current user
          description: |
            Update which asset page is shown to the current user per default. For instance, the user would see graphs per default when clicking on an asset (now the default is the Context page).

            This endpoint sets the default asset view for the current user session if `use_as_default` is true.
            If `use_as_default` is `false`, it clears the session variable for the default asset view.

            ## Example values for `default_asset_view`:
            - "Audit Log"
            - "Context"
            - "Graphs"
            - "Properties"
            - "Status"
          security:
            - ApiKeyAuth: []
          requestBody:
            required: true
            content:
              application/json:
                schema: DefaultAssetViewJSONSchema
                examples:
                  default_asset_view:
                    summary: Setting the user's default asset view to "Graphs"
                    value:
                      default_asset_view: "Graphs"
                      use_as_default: true
                  resetting_default_view:
                    summary: resetting the user's default asset view (will return to use system default)
                    value:
                      use_as_default: false
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  examples:
                    message:
                      summary: Message
                      value:
                        message: "Default asset view updated successfully."
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Assets
        """
        # Update the request.values
        request_values = request.values.copy()
        request_values.update(kwargs)
        request.values = request_values

        use_as_default = kwargs.get("use_as_default", True)
        if use_as_default:
            # Set the default asset view for the current user session
            set_session_variables(
                "default_asset_view",
            )
        else:
            # Remove the default asset view from the session
            clear_session(keys_to_clear=["default_asset_view"])

        return {
            "message": "Default asset view updated successfully.",
        }, 200

    @route("/<id>/schedules/trigger", methods=["POST"])
    @use_args(AssetTriggerSchema(), location="args_and_json", as_kwargs=True)
    # Simplification of checking for create-children access on each of the flexible sensors,
    # which assumes each of the flexible sensors belongs to the given asset.
    @permission_required_for_context("create-children", ctx_arg_name="asset")
    def trigger_schedule(
        self,
        asset: GenericAsset,
        start_of_schedule: datetime,
        duration: timedelta,
        belief_time: datetime | None = None,
        flex_model: dict | None = None,
        flex_context: dict | None = None,
        sequential: bool = False,
        **kwargs,
    ):
        """
        .. :quickref: Schedules; Trigger scheduling job for any number of devices
        ---
        post:
          summary: Trigger scheduling job for any number of devices
          description: |
            Trigger FlexMeasures to create a schedule for this asset.
            The flex-model needs to reference the power sensors of flexible devices, which must belong to the given asset,
            either directly or indirectly, by being assigned to one of the asset's (grand)children.

            In this request, you can describe:

            - the schedule's main features (when does it start, what unit should it report, prior to what time can we assume knowledge)
            - the flexibility models for the asset's relevant sensors (state and constraint variables, e.g. current state of charge of a battery, or connection capacity)
            - the flexibility context which the asset operates in (other sensors under the same EMS which are relevant, e.g. prices)

            For details on flexibility model and context, [see describing_flexibility](https://flexmeasures.readthedocs.io/stable/features/scheduling.html#describing-flexibility).
            Below, we'll also list some examples.
            The schemas we use in this endpoint documentation do not describe the full flexibility model and context (as the docs do), as these are very flexible (e.g. fixed values or sensors). The examples below illustrate how to describe a flexibility model and context.

            > **Note:** This endpoint supports scheduling an EMS with multiple flexible devices at once.
            > It can do so jointly (the default) or sequentially
            > (considering previously scheduled sensors as inflexible).
            > To use sequential scheduling, use ``sequential=true`` in the JSON body.

            The length of the schedule can be set explicitly through the 'duration' field.
            Otherwise, it is set by the config setting [see planning_horizon_config](https://flexmeasures.readthedocs.io/stable/configuration.html#flexmeasures-planning-horizon), which defaults to 48 hours.
            If the flex-model contains targets that lie beyond the planning horizon, the length of the schedule is extended to accommodate them.
            Finally, the schedule length is limited by [see max_planning_horizon_config](https://flexmeasures.readthedocs.io/stable/configuration.html#flexmeasures-max-planning-horizon), which defaults to 2520 steps of each sensor's resolution.
            Targets that exceed the max planning horizon are not accepted.

            The appropriate algorithm is chosen by FlexMeasures (based on asset type).
            It's also possible to use custom schedulers and custom flexibility models, [see plugin_customization](https://flexmeasures.readthedocs.io/stable/plugin/customisation.html#plugin-customization).

            If you have ideas for algorithms that should be part of FlexMeasures, let us know: [https://flexmeasures.io/get-in-touch/](https://flexmeasures.io/get-in-touch/)
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              required: true
              description: ID of the asset to schedule.
              schema:
                type: integer

          requestBody:
              content:
                  application/json:
                    schema: AssetTriggerOpenAPISchema
                    examples:
                      storage_asset:
                        description: |
                          This message triggers a schedule for a storage asset (with power sensor 931),
                          starting at 10.00am, with the state of charge (soc) sensor being 74.
                          This also schedules a curtailable production asset (with power sensor 932),
                          whose production forecasts are recorded under sensor 760.

                          Aggregate consumption (of all devices within this EMS) should be priced by sensor 9,
                          and aggregate production should be priced by sensor 10,
                          where the aggregate power flow in the EMS is described by the sum over sensors 13, 14, 15,
                          and the two power sensors (931 and 932) of the flexible devices being optimized (referenced in the flex-model).

                          The battery consumption power capacity is limited by sensor 42 and the production capacity is constant (30 kW).
                          Finally, the site consumption capacity is limited by sensor 32.
                        value:
                          "start": "2015-06-02T10:00:00+00:00"
                          "flex-model":
                            - "sensor": 931
                              "soc-at-start": 12.1
                              "state-of-charge": {"sensor": 74}
                              "soc-unit": "kWh"
                              "power-capacity": "25kW"
                              "consumption-capacity" : {"sensor": 42}
                              "production-capacity" : "30 kW"
                            - "sensor": 932
                              "consumption-capacity": "0 kW"
                              "production-capacity": {"sensor": 760}
                          "flex-context":
                            "consumption-price": {"sensor": 9}
                            "production-price": {"sensor": 10}
                            "inflexible-device-sensors": [13, 14, 15]
                            "site-power-capacity": "100kW"
                            "site-production-capacity": "80kW"
                            "site-consumption-capacity": {"sensor": 32}

          responses:
              200:
                description: PROCESSED
                content:
                  application/json:
                    schema:
                      type: object
                    examples:
                      successful_response:
                        description: |
                          This message indicates that the scheduling request has been processed without any error.
                          A scheduling job has been created with some Universally Unique Identifier (UUID),
                          which will be picked up by a worker.
                          The given UUID may be used to obtain the resulting schedule for each flexible device: [see /sensors/schedules/.](#/Sensors/get_api_v3_0_sensors__id__schedules__uuid_).
                        value:
                          status: PROCESSED
                          schedule: "364bfd06-c1fa-430b-8d25-8f5a547651fb"
                          message: "Request has been processed."
              400:
                description: INVALID_DATA
              401:
                description: UNAUTHORIZED
              403:
                description: INVALID_SENDER
              405:
                description: INVALID_METHOD
              422:
                description: UNPROCESSABLE_ENTITY

          tags:
              - Assets
        """
        end_of_schedule = start_of_schedule + duration

        scheduler_kwargs = dict(
            start=start_of_schedule,
            end=end_of_schedule,
            belief_time=belief_time,  # server time if no prior time was sent
            flex_model=flex_model,
            flex_context=flex_context,
        )
        if sequential:
            f = create_sequential_scheduling_job
        else:
            f = create_simultaneous_scheduling_job
        try:
            job = f(asset=asset, enqueue=True, **scheduler_kwargs)
        except ValidationError as err:
            return invalid_flex_config(err.messages)
        except ValueError as err:
            return invalid_flex_config(str(err))

        response = dict(schedule=job.id)
        d, s = request_processed()
        return dict(**response, **d), s

    @route("/<id>/kpis", methods=["GET"])
    @use_kwargs(
        {
            "asset": AssetIdField(
                data_key="id", status_if_not_found=HTTPStatus.NOT_FOUND
            )
        },
        location="path",
    )
    @use_kwargs(
        {
            "start": AwareDateTimeField(required=True),
            "end": AwareDateTimeField(required=True),
        },
        location="query",
    )
    def get_kpis(self, id: int, asset: GenericAsset, start, end):
        """
        .. :quickref: Assets; Get daily KPIs for an asset.
        ---
        get:
          summary: Get daily KPIs for an asset.
          description: |
            Gets statistics for sensors for the given time range.
            The asset attribute `sensors_to_show_as_kpis` determines which sensors are considered.
            Read more [here](https://flexmeasures.readthedocs.io/latest/views/asset-data.html#showing-daily-kpis).

            The sensors are expected to have a daily resolution, suitable for KPIs.
            Each sensor has a preferred function to downsample the daily values to the KPI value.

            This endpoint returns a list of KPIs for the asset.
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              required: true
              schema:
                type: integer
            - in: query
              name: start
              schema:
                type: string
                format: date-time
              description: Start time for KPI calculation
              example: "2015-06-02T00:00:00+00:00"
            - in: query
              name: end
              schema:
                type: string
                format: date-time
              description: End time for KPI calculation
              example: "2015-06-09T00:00:00+00:00"
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  examples:
                    kpi_response:
                      summary: KPI response
                      value:
                        data:
                          - sensor: 145046
                            title: My KPI
                            unit: MW
                            downsample_value: 0
                            downsample_function: sum
                          - sensor: 141053
                            title: Raw PowerKPI
                            unit: kW
                            downsample_value: 816.67
                            downsample_function: sum
            400:
              description: INVALID_DATA
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            405:
              description: INVALID_METHOD
          tags:
            - Assets
        """
        check_access(asset, "read")
        asset_kpis = asset.sensors_to_show_as_kpis
        kpis = []
        for kpi in asset_kpis:
            sensor = Sensor.query.get(kpi["sensor"])
            sensor_stats = get_sensor_stats(sensor, start, end, sort_keys=False)

            downsample_function, downsample_value = get_downsample_function_and_value(
                kpi, sensor, sensor_stats
            )
            kpi_dict = {
                "title": kpi["title"],
                "unit": sensor.unit,
                "sensor": sensor.id,
                "downsample_value": round(float(downsample_value), 2),
                "downsample_function": downsample_function,
            }
            kpis.append(kpi_dict)
        return dict(data=kpis), 200
