from marshmallow import validates, ValidationError, validates_schema, fields, validate

from flexmeasures.data import ma
from flexmeasures.data.models.assets import Asset, AssetType
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import User
from flexmeasures.data.schemas.sensors import SensorSchemaMixin
from flexmeasures.data.schemas.utils import MarshmallowClickMixin


class LatitudeField(MarshmallowClickMixin, fields.Float):
    """Field that deserializes to a latitude with 7 places."""

    def __init__(self, *args, **kwargs):
        super().__init__(validate=validate.Range(min=-90, max=90))

    def _deserialize(self, value, attr, obj, **kwargs) -> float:
        return round(super()._deserialize(value, attr, obj, **kwargs), 7)


class LongitudeField(MarshmallowClickMixin, fields.Float):
    """Field that deserializes to a longitude with 7 places."""

    def __init__(self, *args, **kwargs):
        super().__init__(validate=validate.Range(min=-180, max=180))

    def _deserialize(self, value, attr, obj, **kwargs) -> float:
        return round(super()._deserialize(value, attr, obj, **kwargs), 7)


class AssetSchema(SensorSchemaMixin, ma.SQLAlchemySchema):
    """
    Asset schema, with validations.

    TODO: deprecate, as it is based on legacy data model. Move some attributes to SensorSchema.
    """

    class Meta:
        model = Asset

    @validates("name")
    def validate_name(self, name: str):
        asset = Asset.query.filter(Asset.name == name).one_or_none()
        if asset:
            raise ValidationError(f"An asset with the name {name} already exists.")

    @validates("owner_id")
    def validate_owner(self, owner_id: int):
        owner = User.query.get(owner_id)
        if not owner:
            raise ValidationError(f"Owner with id {owner_id} doesn't exist.")
        if not owner.account.has_role("Prosumer"):
            raise ValidationError(
                "Asset owner's account must have role 'Prosumer'."
                f" User {owner_id}'s account has roles: {'.'.join([r.name for r in owner.account.account_roles])}."
            )

    @validates("market_id")
    def validate_market(self, market_id: int):
        sensor = Sensor.query.get(market_id)
        if not sensor:
            raise ValidationError(f"Market with id {market_id} doesn't exist.")

    @validates("asset_type_name")
    def validate_asset_type(self, asset_type_name: str):
        asset_type = AssetType.query.get(asset_type_name)
        if not asset_type:
            raise ValidationError(f"Asset type {asset_type_name} doesn't exist.")

    @validates_schema(skip_on_field_errors=False)
    def validate_soc_constraints(self, data, **kwargs):
        if "max_soc_in_mwh" in data and "min_soc_in_mwh" in data:
            if data["max_soc_in_mwh"] < data["min_soc_in_mwh"]:
                errors = {
                    "max_soc_in_mwh": "This value must be equal or higher than the minimum soc."
                }
                raise ValidationError(errors)

    id = ma.auto_field()
    display_name = fields.Str(validate=validate.Length(min=4))
    capacity_in_mw = fields.Float(required=True, validate=validate.Range(min=0.0001))
    min_soc_in_mwh = fields.Float(validate=validate.Range(min=0))
    max_soc_in_mwh = fields.Float(validate=validate.Range(min=0))
    soc_in_mwh = ma.auto_field()
    soc_datetime = ma.auto_field()
    soc_udi_event_id = ma.auto_field()
    latitude = LatitudeField()
    longitude = LongitudeField()
    asset_type_name = ma.auto_field(required=True)
    owner_id = ma.auto_field(required=True)
    market_id = ma.auto_field(required=True)
