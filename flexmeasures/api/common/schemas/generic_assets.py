from flask import abort
from marshmallow import fields
from sqlalchemy import select

from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset


class AssetIdField(fields.Integer):
    """
    Field that represents a generic asset ID. It de-serializes from the asset id to an asset instance.
    """

    def _deserialize(self, asset_id: int, attr, obj, **kwargs) -> GenericAsset:
        asset: GenericAsset = db.session.execute(
            select(GenericAsset).filter_by(id=int(asset_id))
        ).scalar_one_or_none()
        if asset is None:
            raise abort(404, f"GenericAsset {asset_id} not found")
        return asset

    def _serialize(self, asset: GenericAsset, attr, data, **kwargs) -> int:
        return asset.id
