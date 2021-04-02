from functools import wraps

from flask import current_app, abort
from flask_security import current_user
from flask_json import as_json

from sqlalchemy.exc import IntegrityError
from webargs.flaskparser import use_args
from marshmallow import fields

from flexmeasures.data.services.resources import get_assets
from flexmeasures.data.models.assets import Asset as AssetModel, AssetSchema
from flexmeasures.data.auth_setup import unauthorized_handler
from flexmeasures.data.config import db
from flexmeasures.api.common.responses import required_info_missing


asset_schema = AssetSchema()
assets_schema = AssetSchema(many=True)


@use_args({"owner_id": fields.Int()}, location="query")
@as_json
def get(args):
    """List all assets, or the ones owned by a certain user.
    Raise if a non-admin tries to see assets owned by someone else.
    """
    if "owner_id" in args:
        # get_assets ignores owner_id if user is not admin. Here we want to raise a proper auth error.
        if not (current_user.has_role("admin") or args["owner_id"] == current_user.id):
            return unauthorized_handler(None, [])
        assets = get_assets(owner_id=int(args["owner_id"]))
    else:
        assets = get_assets()

    return assets_schema.dump(assets), 200


@as_json
@use_args(AssetSchema())
def post(asset_data):
    """Create new asset"""

    if current_user.has_role("anonymous"):
        return unauthorized_handler(
            None, []
        )  # Disallow edit access, even to own assets TODO: review, such a role should not exist

    asset = AssetModel(**asset_data)
    db.session.add(asset)
    try:
        db.session.commit()
    except IntegrityError as ie:
        return dict(message="Duplicate asset already exists", detail=ie._message()), 400

    return asset_schema.dump(asset), 201


def load_asset(admins_only: bool = False):
    """Decorator which loads an asset.
    Raises 400 if that is not possible due to wrong parameters.
    Raises 404 if asset not found.
    Raises 403 if unauthorized:
    Only admins (or owners if admins_only is False) can access the asset.
    The admins_only parameter can be used if not even the user themselves
    should be allowed.

        @app.route('/asset/<id>')
        @check_asset
        def get_asset(asset):
            return asset_schema.dump(asset), 200

    The route must specify one parameter ― id.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_endpoint(*args, **kwargs):

            args = list(args)
            if len(args) == 0:
                current_app.logger.warning("Request missing id.")
                return required_info_missing(["id"])
            if len(args) > 1:
                return (
                    dict(
                        status="UNEXPECTED_PARAMS",
                        message="Only expected one parameter (id).",
                    ),
                    400,
                )

            try:
                id = int(args[0])
            except ValueError:
                current_app.logger.warning("Cannot parse ID argument from request.")
                return required_info_missing(["id"], "Cannot parse ID arg as int.")

            asset: AssetModel = AssetModel.query.filter_by(id=int(id)).one_or_none()

            if asset is None:
                raise abort(404, f"Asset {id} not found")

            if not current_user.has_role("admin"):
                if admins_only or asset.owner != current_user:
                    return unauthorized_handler(None, [])

            args = (asset,)
            return fn(*args, **kwargs)

        return decorated_endpoint

    return wrapper


@load_asset()
@as_json
def fetch_one(asset):
    """Fetch a given asset"""
    return asset_schema.dump(asset), 200


@load_asset()
@use_args(AssetSchema(partial=True))
@as_json
def patch(db_asset, asset_data):
    """Update an asset given its identifier"""
    ignored_fields = ["id"]
    for k, v in [(k, v) for k, v in asset_data.items() if k not in ignored_fields]:
        setattr(db_asset, k, v)
    db.session.add(db_asset)
    try:
        db.session.commit()
    except IntegrityError as ie:
        return dict(message="Duplicate asset already exists", detail=ie._message()), 400
    return asset_schema.dump(db_asset), 200


@load_asset(admins_only=True)
@as_json
def delete(asset):
    """Delete a task given its identifier"""
    asset_name = asset.name
    db.session.delete(asset)
    db.session.commit()
    current_app.logger.info("Deleted asset '%s'." % asset_name)
    return {}, 204
