from marshmallow import validates, ValidationError, validates_schema, fields, validate

from flexmeasures.data import ma
from flexmeasures.data.models.assets import Asset, AssetType
from flexmeasures.data.models.markets import Market
from flexmeasures.data.models.user import User
from flexmeasures.data.schemas.sensors import SensorSchemaMixin


class AssetSchema(SensorSchemaMixin, ma.SQLAlchemySchema):
    """
    Asset schema, with validations.
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
        if "Prosumer" not in owner.flexmeasures_roles:
            raise ValidationError(
                "Asset owner must have role 'Prosumer'."
                f" User {owner_id} has roles {[r.name for r in owner.flexmeasures_roles]}."
            )

    @validates("market_id")
    def validate_market(self, market_id: int):
        market = Market.query.get(market_id)
        if not market:
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
    latitude = fields.Float(required=True, validate=validate.Range(min=-90, max=90))
    longitude = fields.Float(required=True, validate=validate.Range(min=-180, max=180))
    asset_type_name = ma.auto_field(required=True)
    owner_id = ma.auto_field(required=True)
    market_id = ma.auto_field(required=True)
