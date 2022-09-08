import json

from flask import current_app
from flask_classful import FlaskView, route
from flask_security import login_required
from flask_json import as_json
from marshmallow import fields
from webargs.flaskparser import use_kwargs, use_args

from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.schemas import AwareDateTimeField
from flexmeasures.data.schemas.generic_assets import GenericAssetSchema as AssetSchema
from flexmeasures.api.common.schemas.generic_assets import AssetIdField
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.ui.utils.view_utils import set_time_range_for_session


asset_schema = AssetSchema()
assets_schema = AssetSchema(many=True)
partial_asset_schema = AssetSchema(partial=True, exclude=["account_id"])


class AssetAPI(FlaskView):
    """
    This API view exposes generic assets.
    Under development until it replaces the original Asset API.
    """

    route_base = "/assets"
    trailing_slash = False

    @route("", methods=["GET"])
    @use_kwargs(
        {
            "account": AccountIdField(
                data_key="account_id", load_default=AccountIdField.load_current
            ),
        },
        location="query",
    )
    @permission_required_for_context("read", arg_name="account")
    @as_json
    def index(self, account: Account):
        """List all assets owned by a certain account.

        .. :quickref: Asset; Download asset list

        This endpoint returns all accessible assets for the account of the user.
        The `account_id` query parameter can be used to list assets from a different account.

        **Example response**

        An example of one asset being returned:

        .. sourcecode:: json

            [
                {
                    "id": 1,
                    "name": "Test battery",
                    "latitude": 10,
                    "longitude": 100,
                    "account_id": 2,
                    "generic_asset_type_id": 1
                }
            ]

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        return assets_schema.dump(account.generic_assets), 200

    @route("/public", methods=["GET"])
    @login_required
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
        assets = GenericAsset.query.filter(GenericAsset.account_id.is_(None)).all()
        return assets_schema.dump(assets), 200

    @route("", methods=["POST"])
    @permission_required_for_context(
        "create-children", arg_loader=AccountIdField.load_current
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
        asset = GenericAsset(**asset_data)
        db.session.add(asset)
        db.session.commit()
        return asset_schema.dump(asset), 201

    @route("/<id>", methods=["GET"])
    @use_kwargs({"asset": AssetIdField(data_key="id")}, location="path")
    @permission_required_for_context("read", arg_name="asset")
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
    @permission_required_for_context("update", arg_name="db_asset")
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
        for k, v in asset_data.items():
            setattr(db_asset, k, v)
        db.session.add(db_asset)
        db.session.commit()
        return asset_schema.dump(db_asset), 200

    @route("/<id>", methods=["DELETE"])
    @use_kwargs({"asset": AssetIdField(data_key="id")}, location="path")
    @permission_required_for_context("delete", arg_name="asset")
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
        asset_name = asset.name
        db.session.delete(asset)
        db.session.commit()
        current_app.logger.info("Deleted asset '%s'." % asset_name)
        return {}, 204

    @route("/<id>/chart/")
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
    @permission_required_for_context("read", arg_name="asset")
    def get_chart(self, id: int, asset: GenericAsset, **kwargs):
        """GET from /assets/<id>/chart

        .. :quickref: Chart; Download a chart with time series
        """
        set_time_range_for_session()
        return json.dumps(asset.chart(**kwargs))

    @route("/<id>/chart_data/")
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
    @permission_required_for_context("read", arg_name="asset")
    def get_chart_data(self, id: int, asset: GenericAsset, **kwargs):
        """GET from /assets/<id>/chart_data

        .. :quickref: Chart; Download time series for use in charts

        Data for use in charts (in case you have the chart specs already).
        """
        sensors = asset.sensors_to_show
        return asset.search_beliefs(sensors=sensors, as_json=True, **kwargs)
