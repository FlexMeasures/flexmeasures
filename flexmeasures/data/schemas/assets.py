from __future__ import annotations

from marshmallow import validates, ValidationError, validates_schema, fields, validate

from flexmeasures.data import ma
from flexmeasures.data.models.assets import Asset, AssetType
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import User
from flexmeasures.data.schemas.sensors import SensorSchemaMixin
from flexmeasures.data.schemas.utils import FMValidationError, MarshmallowClickMixin


class LatitudeLongitudeValidator(validate.Validator):
    """Validator which succeeds if the value passed has at most 7 decimal places."""

    def __init__(self, *, error: str | None = None):
        self.error = error

    def __call__(self, value):
        if not round(value, 7) == value:
            raise FMValidationError(
                "Latitudes and longitudes are limited to 7 decimal places."
            )
        return value


class LatitudeValidator(validate.Validator):
    """Validator which succeeds if the value passed is in the range [-90, 90]."""

    def __init__(self, *, error: str | None = None, allow_none: bool = False):
        self.error = error
        self.allow_none = allow_none

    def __call__(self, value):
        if self.allow_none and value is None:
            return
        if value < -90:
            raise FMValidationError(
                f"Latitude {value} exceeds the minimum latitude of -90 degrees."
            )
        if value > 90:
            raise ValidationError(
                f"Latitude {value} exceeds the maximum latitude of 90 degrees."
            )
        return value


class LongitudeValidator(validate.Validator):
    """Validator which succeeds if the value passed is in the range [-180, 180]."""

    def __init__(self, *, error: str | None = None, allow_none: bool = False):
        self.error = error
        self.allow_none = allow_none

    def __call__(self, value):
        if self.allow_none and value is None:
            return
        if value < -180:
            raise FMValidationError(
                f"Longitude {value} exceeds the minimum longitude of -180 degrees."
            )
        if value > 180:
            raise ValidationError(
                f"Longitude {value} exceeds the maximum longitude of 180 degrees."
            )
        return value


class LatitudeField(MarshmallowClickMixin, fields.Float):
    """Field that deserializes to a latitude float with max 7 decimal places."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Insert validation into self.validators so that multiple errors can be stored.
        self.validators.insert(0, LatitudeLongitudeValidator())
        self.validators.insert(
            0, LatitudeValidator(allow_none=kwargs.get("allow_none", False))
        )


class LongitudeField(MarshmallowClickMixin, fields.Float):
    """Field that deserializes to a longitude float with max 7 decimal places."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Insert validation into self.validators so that multiple errors can be stored.
        self.validators.insert(0, LatitudeLongitudeValidator())
        self.validators.insert(
            0, LongitudeValidator(allow_none=kwargs.get("allow_none", False))
        )


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
    latitude = LatitudeField(allow_none=True)
    longitude = LongitudeField(allow_none=True)
    asset_type_name = ma.auto_field(required=True)
    owner_id = ma.auto_field(required=True)
    market_id = ma.auto_field(required=True)
