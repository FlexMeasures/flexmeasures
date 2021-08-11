from typing import Optional

from marshmallow import validates, ValidationError, fields

from flexmeasures.data import ma
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType


class GenericAssetSchema(ma.SQLAlchemySchema):
    """
    GenericAsset schema, with validations.
    """

    id = ma.auto_field()
    name = fields.Str()
    latitude = ma.auto_field()
    longitude = ma.auto_field()
    generic_asset_type_id = fields.Integer()

    class Meta:
        model = GenericAsset

    @validates("generic_asset_type_id")
    def validate_market(self, generic_asset_type_id: int):
        generic_asset_type = GenericAssetType.query.get(generic_asset_type_id)
        if not generic_asset_type:
            raise ValidationError(
                f"GenericAssetType with id {generic_asset_type_id} doesn't exist."
            )

    @validates("latitude")
    def validate_latitude(self, latitude: Optional[float]):
        """Validate optional latitude."""
        if latitude is None:
            return
        if latitude < -90:
            raise ValidationError(
                f"Latitude {latitude} exceeds the minimum latitude of -90 degrees."
            )
        if latitude > 90:
            raise ValidationError(
                f"Latitude {latitude} exceeds the maximum latitude of 90 degrees."
            )

    @validates("longitude")
    def validate_longitude(self, longitude: Optional[float]):
        """Validate optional longitude."""
        if longitude is None:
            return
        if longitude < -180:
            raise ValidationError(
                f"Longitude {longitude} exceeds the minimum longitude of -180 degrees."
            )
        if longitude > 180:
            raise ValidationError(
                f"Longitude {longitude} exceeds the maximum longitude of 180 degrees."
            )


class GenericAssetTypeSchema(ma.SQLAlchemySchema):
    """
    GenericAssetType schema, with validations.
    """

    id = ma.auto_field()
    name = fields.Str()
    hover_label = ma.auto_field()

    class Meta:
        model = GenericAssetType
