from flask import current_app
from flask_classful import FlaskView, route
from flask_json import as_json
from webargs.flaskparser import use_kwargs, use_args

from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.generic_assets import GenericAsset as AssetModel
from flexmeasures.data.schemas.generic_assets import GenericAssetSchema as AssetSchema
from flexmeasures.api.common.schemas.generic_assets import AssetIdField
from flexmeasures.api.common.schemas.users import AccountIdField


asset_schema = AssetSchema()
assets_schema = AssetSchema(many=True)


class AssetAPI(FlaskView):
    """
    This API view exposes generic assets.
    Under development until it replaces the original Asset API.
    """

    route_base = "/generic_assets"

    @route("/", methods=["GET"])
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
        """List all assets owned by a certain account."""
        return assets_schema.dump(account.generic_assets), 200

    @route("/", methods=["POST"])
    @permission_required_for_context(
        "create-children", arg_loader=AccountIdField.load_current
    )
    @use_args(AssetSchema())
    def post(self, asset_data):
        """Create new asset"""
        asset = AssetModel(**asset_data)
        db.session.add(asset)
        db.session.commit()
        return asset_schema.dump(asset), 201

    @route("/<id>", methods=["GET"])
    @use_kwargs({"asset": AssetIdField(data_key="id")}, location="path")
    @permission_required_for_context("read", arg_name="asset")
    @as_json
    def fetch_one(self, id, asset):
        """Fetch a given asset"""
        return asset_schema.dump(asset), 200

    @route("/<id>", methods=["PATCH"])
    @use_args(AssetSchema(partial=True))
    @use_kwargs({"db_asset": AssetIdField(data_key="id")}, location="path")
    @permission_required_for_context("update", arg_name="db_asset")
    @as_json
    def patch(self, asset_data, id, db_asset):
        """Update an asset given its identifier"""
        ignored_fields = ["id", "account_id"]
        for k, v in [(k, v) for k, v in asset_data.items() if k not in ignored_fields]:
            setattr(db_asset, k, v)
        db.session.add(db_asset)
        db.session.commit()
        return asset_schema.dump(db_asset), 200

    @route("/<id>", methods=["DELETE"])
    @use_kwargs({"asset": AssetIdField(data_key="id")}, location="path")
    @permission_required_for_context("delete", arg_name="asset")
    @as_json
    def delete(self, id, asset):
        """Delete an asset given its identifier"""
        asset_name = asset.name
        db.session.delete(asset)
        db.session.commit()
        current_app.logger.info("Deleted asset '%s'." % asset_name)
        return {}, 204
