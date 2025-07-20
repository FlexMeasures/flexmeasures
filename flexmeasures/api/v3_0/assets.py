from __future__ import annotations
import json
from datetime import datetime, timedelta
from http import HTTPStatus
from humanize import naturaldelta

from flask import current_app, request
from flask_classful import FlaskView, route
from flask_login import current_user
from flask_security import auth_required
from flask_json import as_json
from flask_sqlalchemy.pagination import SelectPagination

from marshmallow import fields, ValidationError
import marshmallow.validate as validate

from webargs.flaskparser import use_kwargs, use_args
from sqlalchemy import select, delete, func, or_

from flexmeasures.data.services.sensors import (
    build_asset_jobs_data,
)
from flexmeasures.data.services.job_cache import NoRedisConfigured
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.queries.generic_assets import query_assets_by_search_terms
from flexmeasures.data.schemas import AwareDateTimeField
from flexmeasures.data.schemas.generic_assets import (
    GenericAssetSchema as AssetSchema,
    GenericAssetIdField as AssetIdField,
)
from flexmeasures.data.schemas.scheduling import AssetTriggerSchema
from flexmeasures.data.services.scheduling import (
    create_sequential_scheduling_job,
    create_simultaneous_scheduling_job,
)
from flexmeasures.api.common.responses import (
    invalid_flex_config,
    request_processed,
)
from flexmeasures.api.common.schemas.search import SearchFilterField
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.utils.coding_utils import flatten_unique
from flexmeasures.ui.utils.view_utils import clear_session, set_session_variables
from flexmeasures.auth.policy import check_access
from werkzeug.exceptions import Forbidden, Unauthorized
from flexmeasures.data.schemas.sensors import SensorSchema
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.scheduling import DBFlexContextSchema
from flexmeasures.utils.time_utils import naturalized_datetime_str

asset_schema = AssetSchema()
assets_schema = AssetSchema(many=True)
sensor_schema = SensorSchema()
sensors_schema = SensorSchema(many=True)
partial_asset_schema = AssetSchema(partial=True, exclude=["account_id"])


def get_accessible_accounts() -> list[Account]:
    accounts = []
    for _account in db.session.scalars(select(Account)).all():
        try:
            check_access(_account, "read")
            accounts.append(_account)
        except (Forbidden, Unauthorized):
            pass

    return accounts


class AssetAPI(FlaskView):
    """
    This API view exposes generic assets.
    """

    route_base = "/assets"
    trailing_slash = False
    decorators = [auth_required()]

    @route("", methods=["GET"])
    @use_kwargs(
        {
            "account": AccountIdField(data_key="account_id", load_default=None),
            "all_accessible": fields.Bool(
                data_key="all_accessible", load_default=False
            ),
            "include_public": fields.Bool(
                data_key="include_public", load_default=False
            ),
            "page": fields.Int(required=False, validate=validate.Range(min=1)),
            "per_page": fields.Int(
                required=False, validate=validate.Range(min=1), load_default=10
            ),
            "filter": SearchFilterField(required=False),
            "sort_by": fields.Str(
                required=False,
                validate=validate.OneOf(["id", "name", "owner"]),
            ),
            "sort_dir": fields.Str(
                required=False,
                validate=validate.OneOf(["asc", "desc"]),
            ),
        },
        location="query",
    )
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
        """List all assets owned  by user's accounts, or a certain account or all accessible accounts.

        .. :quickref: Asset; Download asset list

        This endpoint returns all accessible assets by accounts.
        The `account_id` query parameter can be used to list assets from any account (if the user is allowed to read them). Per default, the user's account is used.
        Alternatively, the `all_accessible` query parameter can be used to list assets from all accounts the current_user has read-access to, plus all public assets. Defaults to `false`.
        The `include_public` query parameter can be used to include public assets in the response. Defaults to `false`.

        The endpoint supports pagination of the asset list using the `page` and `per_page` query parameters.

            - If the `page` parameter is not provided, all assets are returned, without pagination information. The result will be a list of assets.
            - If a `page` parameter is provided, the response will be paginated, showing a specific number of assets per page as defined by `per_page` (default is 10).
            - If a search 'filter' such as 'solar "ACME corp"' is provided, the response will filter out assets where each search term is either present in their name or account name.
              The response schema for pagination is inspired by https://datatables.net/manual/server-side#Returned-data


        **Example response**

        An example of one asset being returned in a paginated response:

        .. sourcecode:: json

            {
                "data" : [
                    {
                      "id": 1,
                      "name": "Test battery",
                      "latitude": 10,
                      "longitude": 100,
                      "account_id": 2,
                      "generic_asset_type": {"id": 1, "name": "battery"}
                    }
                ],
                "num-records" : 1,
                "filtered-records" : 1

            }

        If no pagination is requested, the response only consists of the list under the "data" key.

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
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
    @use_kwargs(
        {
            "page": fields.Int(
                required=False, validate=validate.Range(min=1), dump_default=1
            ),
            "per_page": fields.Int(
                required=False, validate=validate.Range(min=1), dump_default=10
            ),
            "filter": SearchFilterField(required=False),
            "sort_by": fields.Str(
                required=False,
                validate=validate.OneOf(["id", "name", "resolution"]),
            ),
            "sort_dir": fields.Str(
                required=False,
                validate=validate.OneOf(["asc", "desc"]),
            ),
        },
        location="query",
    )
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
        List all sensors under an asset.

         .. :quickref: Asset; Return all sensors under an asset.

        This endpoint returns all sensors under an asset.

        The endpoint supports pagination of the asset list using the `page` and `per_page` query parameters.

        - If the `page` parameter is not provided, all sensors are returned, without pagination information. The result will be a list of sensors.
        - If a `page` parameter is provided, the response will be paginated, showing a specific number of assets per page as defined by `per_page` (default is 10).
        The response schema for pagination is inspired by https://datatables.net/manual/server-side#Returned-data


        **Example response**

        An example of one asset being returned in a paginated response:

        .. sourcecode:: json

            {
                "data" : [
                    {
                      "id": 1,
                      "name": "Test battery",
                      "latitude": 10,
                      "longitude": 100,
                      "account_id": 2,
                      "generic_asset_type": {"id": 1, "name": "battery"}
                    }
                ],
                "num-records" : 1,
                "filtered-records" : 1

            }

        If no pagination is requested, the response only consists of the list under the "data" key.

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
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
        """Return all public assets.

        .. :quickref: Asset; Return all public assets.

        This endpoint returns all public assets.

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST
        :status 401: UNAUTHORIZED
        :status 422: UNPROCESSABLE_ENTITY
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
        """Create new asset.

        .. :quickref: Asset; Create a new asset

        This endpoint creates a new asset.

        **Example request A**

        .. sourcecode:: json

            {
                "name": "Test battery",
                "generic_asset_type_id": 2,
                "account_id": 2,
                "latitude": 40,
                "longitude": 170.3,
            }


        The newly posted asset is returned in the response.

        **Example request B**

        Alternatively, set the ``parent_asset_id`` to make the new asset a child of another asset.
        For example, to set asset 10 as its parent:

        .. sourcecode:: json
            :emphasize-lines: 5

            {
                "name": "Test battery",
                "generic_asset_type_id": 2,
                "account_id": 2,
                "parent_asset_id": 10,
                "latitude": 40,
                "longitude": 170.3,
            }


        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 201: CREATED
        :status 400: INVALID_REQUEST
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        asset = GenericAsset(**asset_data)
        db.session.add(asset)
        # assign asset id
        db.session.flush()

        AssetAuditLog.add_record(asset, f"Created asset '{asset.name}': {asset.id}")

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
        """Fetch a given asset.

        .. :quickref: Asset; Get an asset

        This endpoint gets an asset.

        **Example response**

        .. sourcecode:: json

            {
                "generic_asset_type_id": 2,
                "name": "Test battery",
                "id": 1,
                "latitude": 10,
                "longitude": 100,
                "account_id": 1,
            }

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        return asset_schema.dump(asset), 200

    @route("/<id>", methods=["PATCH"])
    @use_args(partial_asset_schema)
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
        """Update an asset given its identifier.

        .. :quickref: Asset; Update an asset

        This endpoint sets data for an existing asset.
        Any subset of asset fields can be sent.

        The following fields are not allowed to be updated:
        - id
        - account_id

        **Example request**

        .. sourcecode:: json

            {
                "latitude": 11.1,
                "longitude": 99.9,
            }


        **Example response**

        The whole asset is returned in the response:

        .. sourcecode:: json

            {
                "generic_asset_type_id": 2,
                "id": 1,
                "latitude": 11.1,
                "longitude": 99.9,
                "name": "Test battery",
                "account_id": 2,
            }

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: UPDATED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        audit_log_data = list()
        for k, v in asset_data.items():
            if getattr(db_asset, k) == v:
                continue
            if k == "attributes":
                current_attributes = getattr(db_asset, k)
                for attr_key, attr_value in v.items():
                    if current_attributes.get(attr_key) != attr_value:
                        audit_log_data.append(
                            f"Updated Attr: {attr_key}, From: {current_attributes.get(attr_key)}, To: {attr_value}"
                        )
                continue
            if k == "flex_context":
                try:
                    # Validate the flex context schema
                    DBFlexContextSchema().load(v)
                except Exception as e:
                    return {"error": str(e)}, 422

            audit_log_data.append(
                f"Updated Field: {k}, From: {getattr(db_asset, k)}, To: {v}"
            )

        # Iterate over each field or attribute updates and create a separate audit log entry for each.
        for event in audit_log_data:
            AssetAuditLog.add_record(db_asset, event)

        for k, v in asset_data.items():
            setattr(db_asset, k, v)
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
        """Delete an asset given its identifier.

        .. :quickref: Asset; Delete an asset

        This endpoint deletes an existing asset, as well as all sensors and measurements recorded for it.

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 204: DELETED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        asset_name, asset_id = asset.name, asset.id
        AssetAuditLog.add_record(asset, f"Deleted asset '{asset_name}': {asset_id}")

        db.session.execute(delete(GenericAsset).filter_by(id=asset.id))
        db.session.commit()
        current_app.logger.info("Deleted asset '%s'." % asset_name)
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
    @use_kwargs(
        {
            "event_starts_after": AwareDateTimeField(format="iso", required=False),
            "event_ends_before": AwareDateTimeField(format="iso", required=False),
            "beliefs_after": AwareDateTimeField(format="iso", required=False),
            "beliefs_before": AwareDateTimeField(format="iso", required=False),
            "include_data": fields.Boolean(required=False),
            "combine_legend": fields.Boolean(required=False, load_default=True),
            "dataset_name": fields.Str(required=False),
            "height": fields.Str(required=False),
            "width": fields.Str(required=False),
            "chart_type": fields.Str(required=False),
        },
        location="query",
    )
    @permission_required_for_context("read", ctx_arg_name="asset")
    def get_chart(self, id: int, asset: GenericAsset, **kwargs):
        """GET from /assets/<id>/chart

        .. :quickref: Chart; Download a chart with time series
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
        },
        location="query",
    )
    @permission_required_for_context("read", ctx_arg_name="asset")
    def get_chart_data(self, id: int, asset: GenericAsset, **kwargs):
        """GET from /assets/<id>/chart_data

        .. :quickref: Chart; Download time series for use in charts

        Data for use in charts (in case you have the chart specs already).
        """
        sensors = flatten_unique(asset.validate_sensors_to_show())
        return asset.search_beliefs(sensors=sensors, as_json=True, **kwargs)

    @route("/<id>/auditlog")
    @use_kwargs(
        {"asset": AssetIdField(data_key="id")},
        location="path",
    )
    @permission_required_for_context("read", ctx_arg_name="asset")
    @use_kwargs(
        {
            "page": fields.Int(
                required=False, validate=validate.Range(min=1), load_default=1
            ),
            "per_page": fields.Int(
                required=False, validate=validate.Range(min=1), load_default=10
            ),
            "filter": SearchFilterField(required=False),
            "sort_by": fields.Str(
                required=False,
                validate=validate.OneOf(["event_datetime"]),
            ),
            "sort_dir": fields.Str(
                required=False,
                validate=validate.OneOf(["asc", "desc"]),
            ),
        },
        location="query",
    )
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
        """API endpoint to get history of asset related actions.

        .. :quickref: Asset; Get audit log

        The endpoint is paginated and supports search filters.

            - If the `page` parameter is not provided, all audit logs are returned paginated by `per_page` (default is 10).
            - If a `page` parameter is provided, the response will be paginated, showing a specific number of assets per page as defined by `per_page` (default is 10).
            - If `sort_by` (field name) and `sort_dir` ("asc" or "desc") are provided, the list will be sorted.
            - If a search 'filter' is provided, the response will filter out audit logs where each search term is either present in the event or active user name.
              The response schema for pagination is inspired by https://datatables.net/manual/server-side


        **Example response**

        .. sourcecode:: json
            {
                "data" : [
                    {
                        'event': 'Asset test asset deleted',
                        'event_datetime': '2021-01-01T00:00:00',
                        'active_user_name': 'Test user',
                    }
                ],
                "num-records" : 1,
                "filtered-records" : 1
            }

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
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
        """API endpoint to get all jobs of an asset.

        .. :quickref: Asset; Get asset jobs

        The response will be a list of jobs.
        Note that jobs in Redis have a limited TTL, so not all past jobs will be listed.

        **Example response**

        .. sourcecode:: json
            {
                "jobs": [
                    {
                        "job_id": 1,
                        "queue": "scheduling",
                        "asset_or_sensor_type": "asset",
                        "asset_id": 1,
                        "status": "finished",
                        "err": None,
                        "enqueued_at": "2023-10-01T00:00:00",
                        "metadata_hash": "abc123",
                    }
                ],
                "redis_connection_err": null
            }

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
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
    @use_kwargs(
        {
            "default_asset_view": fields.Str(
                required=True,
                validate=validate.OneOf(
                    [
                        "Audit Log",
                        "Context",
                        "Graphs",
                        "Properties",
                        "Status",
                    ]
                ),
            ),
            "use_as_default": fields.Bool(required=False, load_default=True),
        },
        location="json",
    )
    def update_default_asset_view(self, **kwargs):
        """Update the default asset view for the current user session.

        .. :quickref: Asset; Update the default asset view

        **Example request**

        .. sourcecode:: json

            {
                "default_asset_view": "Graphs",
                "use_as_default": true
            }

        **Example response**

        .. sourcecode:: json
            {
                "message": "Default asset view updated successfully."
            }

        This endpoint sets the default asset view for the current user session if use_as_default is true.
        If use_as_default is false, it clears the session variable for the default asset view.

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
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
        Trigger FlexMeasures to create a schedule for a collection of flexible and inflexible devices.

        .. :quickref: Schedule; Trigger scheduling job for any number of devices

        Trigger FlexMeasures to create a schedule for this asset.
        The flex-model references the power sensors of flexible devices, which must belong to the given asset,
        either directly or indirectly, by being assigned to one of the asset's (grand)children.

        In this request, you can describe:

        - the schedule's main features (when does it start, what unit should it report, prior to what time can we assume knowledge)
        - the flexibility models for the asset's relevant sensors (state and constraint variables, e.g. current state of charge of a battery, or connection capacity)
        - the flexibility context which the asset operates in (other sensors under the same EMS which are relevant, e.g. prices)

        For details on flexibility model and context, see :ref:`describing_flexibility`.
        Below, we'll also list some examples.

        .. note:: This endpoint supports scheduling an EMS with multiple flexible devices at once.
                  It can do so jointly (the default) or sequentially
                  (considering previously scheduled sensors as inflexible).
                  To use sequential scheduling, use ``sequential=true`` in the JSON body.

        The length of the schedule can be set explicitly through the 'duration' field.
        Otherwise, it is set by the config setting :ref:`planning_horizon_config`, which defaults to 48 hours.
        If the flex-model contains targets that lie beyond the planning horizon, the length of the schedule is extended to accommodate them.
        Finally, the schedule length is limited by :ref:`max_planning_horizon_config`, which defaults to 2520 steps of each sensor's resolution.
        Targets that exceed the max planning horizon are not accepted.

        The appropriate algorithm is chosen by FlexMeasures (based on asset type).
        It's also possible to use custom schedulers and custom flexibility models, see :ref:`plugin_customization`.

        If you have ideas for algorithms that should be part of FlexMeasures, let us know: https://flexmeasures.io/get-in-touch/

        **Example request**

        This message triggers a schedule for a storage asset (with power sensor 931),
        starting at 10.00am, when the state of charge (soc) should be assumed to be 12.1 kWh,
        and also schedules a curtailable production asset (with power sensor 932),
        whose production forecasts are recorded under sensor 760.

        Aggregate consumption (of all devices within this EMS) should be priced by sensor 9,
        and aggregate production should be priced by sensor 10,
        where the aggregate power flow in the EMS is described by the sum over sensors 13, 14, 15,
        and the two power sensors (931 and 932) of the flexible devices being optimized (referenced in the flex-model).

        The battery consumption power capacity is limited by sensor 42 and the production capacity is constant (30 kW).
        Finally, the site consumption capacity is limited by sensor 32.

        .. code-block:: json

            {
                "start": "2015-06-02T10:00:00+00:00",
                "flex-model": [
                    {
                        "sensor": 931,
                        "soc-at-start": 12.1,
                        "soc-unit": "kWh",
                        "power-capacity": "25kW",
                        "consumption-capacity" : {"sensor": 42},
                        "production-capacity" : "30 kW"
                    },
                    {
                        "sensor": 932,
                        "consumption-capacity": "0 kW",
                        "production-capacity": {"sensor": 760},
                    }
                ],
                "flex-context": {
                    "consumption-price-sensor": 9,
                    "production-price-sensor": 10,
                    "inflexible-device-sensors": [13, 14, 15],
                    "site-power-capacity": "100kW",
                    "site-production-capacity": "80kW",
                    "site-consumption-capacity": {"sensor": 32}
                }
            }

        **Example response**

        This message indicates that the scheduling request has been processed without any error.
        A scheduling job has been created with some Universally Unique Identifier (UUID),
        which will be picked up by a worker.
        The given UUID may be used to obtain the resulting schedule for each flexible device: see /sensors/<id>/schedules/<uuid>.

        .. sourcecode:: json

            {
                "status": "PROCESSED",
                "schedule": "364bfd06-c1fa-430b-8d25-8f5a547651fb",
                "message": "Request has been processed."
            }

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_DATA
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 405: INVALID_METHOD
        :status 422: UNPROCESSABLE_ENTITY
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
