from __future__ import annotations

import json

from flask import current_app
from flask_classful import FlaskView, route
from flask_login import current_user
from flask_security import auth_required
from flask_json import as_json
from flask_sqlalchemy.pagination import SelectPagination

from marshmallow import fields
import marshmallow.validate as validate

from webargs.flaskparser import use_kwargs, use_args
from sqlalchemy import select, delete, func

from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.queries.generic_assets import query_assets_by_search_terms
from flexmeasures.data.schemas import AwareDateTimeField
from flexmeasures.data.schemas.generic_assets import GenericAssetSchema as AssetSchema
from flexmeasures.api.common.schemas.generic_assets import (
    AssetIdField,
    SearchFilterField,
)
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.utils.coding_utils import flatten_unique
from flexmeasures.ui.utils.view_utils import set_session_variables
from flexmeasures.auth.policy import check_access
from werkzeug.exceptions import Forbidden, Unauthorized


asset_schema = AssetSchema()
assets_schema = AssetSchema(many=True)
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
        },
        location="query",
    )
    @use_kwargs(
        {
            "all_accessible": fields.Bool(
                data_key="all_accessible", load_default=False
            ),
        },
        location="query",
    )
    @use_kwargs(
        {
            "page": fields.Int(
                required=False, validate=validate.Range(min=1), default=1
            ),
            "per_page": fields.Int(
                required=False, validate=validate.Range(min=1), default=10
            ),
            "filter": SearchFilterField(required=False, default=None),
        },
        location="query",
    )
    @as_json
    def index(
        self,
        account: Account | None,
        all_accessible: bool,
        page: int | None = None,
        per_page: int | None = None,
        filter: list[str] | None = None,
    ):
        """List all assets owned  by user's accounts, or a certain account or all accessible accounts.

        .. :quickref: Asset; Download asset list

        This endpoint returns all accessible assets by accounts.
        The `account_id` query parameter can be used to list assets from any account (if the user is allowed to read them). Per default, the user's account is used.
        Alternatively, the `all_accessible` query parameter can be used to list assets from all accounts the current_user has read-access to, plus all public assets. Defaults to `false`.

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
        if all_accessible:
            filter_statement = filter_statement | GenericAsset.account_id.is_(None)

        num_records = db.session.scalar(
            select(func.count(GenericAsset.id)).where(filter_statement)
        )

        query = query_assets_by_search_terms(
            search_terms=filter, filter_statement=filter_statement
        )
        if page is None:
            response = asset_schema.dump(db.session.scalars(query).all(), many=True)
        else:
            if per_page is None:
                per_page = 10

            select_pagination: SelectPagination = db.paginate(
                query, per_page=per_page, page=page
            )
            response = {
                "data": asset_schema.dump(select_pagination.items, many=True),
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

        **Example request**

        .. sourcecode:: json

            {
                "name": "Test battery",
                "generic_asset_type_id": 2,
                "account_id": 2,
                "latitude": 40,
                "longitude": 170.3,
            }


        The newly posted asset is returned in the response.

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 201: CREATED
        :status 400: INVALID_REQUEST
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        inflexible_sensor_ids = asset_data.pop("inflexible_device_sensor_ids", [])
        asset = GenericAsset(**asset_data)
        db.session.add(asset)
        # assign asset id
        db.session.flush()

        asset.set_inflexible_sensors(inflexible_sensor_ids)
        db.session.commit()

        AssetAuditLog.add_record(asset, f"Created asset '{asset.name}': {asset.id}")

        return asset_schema.dump(asset), 201

    @route("/<id>", methods=["GET"])
    @use_kwargs({"asset": AssetIdField(data_key="id")}, location="path")
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
    @use_kwargs({"db_asset": AssetIdField(data_key="id")}, location="path")
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
        inflexible_sensor_ids = asset_data.pop("inflexible_device_sensor_ids", [])
        db_asset.set_inflexible_sensors(inflexible_sensor_ids)

        audit_log_data = list()
        for k, v in asset_data.items():
            if getattr(db_asset, k) == v:
                continue
            if k == "attributes":
                current_attributes = getattr(db_asset, k)
                for attr_key, attr_value in v.items():
                    if current_attributes.get(attr_key) != attr_value:
                        audit_log_data.append(
                            f"Attr: {attr_key}, From: {current_attributes.get(attr_key)}, To: {attr_value}"
                        )
                continue
            audit_log_data.append(f"Field: {k}, From: {getattr(db_asset, k)}, To: {v}")

        # Iterate over each field or attribute updates and create a separate audit log entry for each.
        for event in audit_log_data:
            audit_log_event = (
                f"Updated asset '{db_asset.name}': {db_asset.id}; fields: {event}"
            )
            AssetAuditLog.add_record(db_asset, audit_log_event)

        for k, v in asset_data.items():
            setattr(db_asset, k, v)
        db.session.add(db_asset)
        db.session.commit()
        return asset_schema.dump(db_asset), 200

    @route("/<id>", methods=["DELETE"])
    @use_kwargs({"asset": AssetIdField(data_key="id")}, location="path")
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
        {"asset": AssetIdField(data_key="id")},
        location="path",
    )
    @use_kwargs(
        {
            "event_starts_after": AwareDateTimeField(format="iso", required=False),
            "event_ends_before": AwareDateTimeField(format="iso", required=False),
            "beliefs_after": AwareDateTimeField(format="iso", required=False),
            "beliefs_before": AwareDateTimeField(format="iso", required=False),
            "include_data": fields.Boolean(required=False),
            "dataset_name": fields.Str(required=False),
            "height": fields.Str(required=False),
            "width": fields.Str(required=False),
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
        {"asset": AssetIdField(data_key="id")},
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
        sensors = flatten_unique(asset.sensors_to_show)
        return asset.search_beliefs(sensors=sensors, as_json=True, **kwargs)

    @route("/<id>/auditlog")
    @use_kwargs(
        {"asset": AssetIdField(data_key="id")},
        location="path",
    )
    @permission_required_for_context("read", ctx_arg_name="asset")
    @as_json
    def auditlog(self, id: int, asset: GenericAsset):
        """API endpoint to get history of asset related actions.
        **Example response**

        .. sourcecode:: json
            [
                {
                    'event': 'Asset test asset deleted',
                    'event_datetime': '2021-01-01T00:00:00',
                    'active_user_name': 'Test user',
                }
            ]

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        audit_logs = (
            db.session.query(AssetAuditLog).filter_by(affected_asset_id=asset.id).all()
        )
        audit_logs = [
            {
                k: getattr(log, k)
                for k in (
                    "event",
                    "event_datetime",
                    "active_user_name",
                    "active_user_id",
                )
            }
            for log in audit_logs
        ]
        return audit_logs, 200
