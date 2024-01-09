from __future__ import annotations
from marshmallow import Schema, fields, validates, ValidationError
from pint import DimensionalityError

import json

from flexmeasures.data import ma
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.utils import (
    FMValidationError,
    MarshmallowClickMixin,
    with_appcontext_if_needed,
)
from flexmeasures.utils.unit_utils import is_valid_unit, ur, units_are_convertible
from flexmeasures.data.schemas.times import DurationField


class JSON(fields.Field):
    def _deserialize(self, value, attr, data, **kwargs) -> dict:
        try:
            return json.loads(value)
        except ValueError:
            raise ValidationError("Not a valid JSON string.")

    def _serialize(self, value, attr, data, **kwargs) -> str:
        return json.dumps(value)


class SensorSchemaMixin(Schema):
    """
    Base sensor schema.

    Here we include all fields which are implemented by timely_beliefs.SensorDBMixin
    All classes inheriting from timely beliefs sensor don't need to repeat these.
    In a while, this schema can represent our unified Sensor class.

    When subclassing, also subclass from `ma.SQLAlchemySchema` and add your own DB model class, e.g.:

        class Meta:
            model = Asset
    """

    id = ma.auto_field(dump_only=True)
    name = ma.auto_field(required=True)
    unit = ma.auto_field(required=True)
    timezone = ma.auto_field()
    event_resolution = DurationField(required=True)
    entity_address = fields.String(dump_only=True)
    attributes = JSON(required=False)

    @validates("unit")
    def validate_unit(self, unit: str):
        if not is_valid_unit(unit):
            raise ValidationError(f"Unit '{unit}' cannot be handled.")


class SensorSchema(SensorSchemaMixin, ma.SQLAlchemySchema):
    """
    Sensor schema, with validations.
    """

    generic_asset_id = fields.Integer(required=True)

    @validates("generic_asset_id")
    def validate_generic_asset(self, generic_asset_id: int):
        generic_asset = GenericAsset.query.get(generic_asset_id)
        if not generic_asset:
            raise ValidationError(
                f"Generic asset with id {generic_asset_id} doesn't exist."
            )

    class Meta:
        model = Sensor


class SensorIdField(MarshmallowClickMixin, fields.Int):
    """Field that deserializes to a Sensor and serializes back to an integer."""

    @with_appcontext_if_needed()
    def _deserialize(self, value: int, attr, obj, **kwargs) -> Sensor:
        """Turn a sensor id into a Sensor."""
        sensor = Sensor.query.get(value)
        if sensor is None:
            raise FMValidationError(f"No sensor found with id {value}.")
        # lazy loading now (sensor is somehow not in session after this)
        sensor.generic_asset
        sensor.generic_asset.generic_asset_type
        return sensor

    def _serialize(self, sensor: Sensor, attr, data, **kwargs) -> int:
        """Turn a Sensor into a sensor id."""
        return sensor.id


class QuantityOrSensor(MarshmallowClickMixin, fields.Field):
    def __init__(self, to_unit: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.to_unit = ur.Quantity(to_unit)

    @with_appcontext_if_needed()
    def _deserialize(
        self, value: str | dict[str, int], attr, obj, **kwargs
    ) -> ur.Quantity | Sensor:
        if isinstance(value, dict):
            if "sensor" not in value:
                raise FMValidationError(
                    "Dictionary provided but `sensor` key not found."
                )

            sensor = Sensor.query.get(value["sensor"])

            if sensor is None:
                raise FMValidationError(f"No sensor found with id {value['sensor']}.")

            # lazy loading now (sensor is somehow not in session after this)
            sensor.generic_asset
            sensor.generic_asset.generic_asset_type

            if not units_are_convertible(sensor.unit, str(self.to_unit.units)):
                raise FMValidationError(
                    f"Cannot convert {sensor.unit} to {self.to_unit.units}"
                )

            return sensor

        elif isinstance(value, str):
            try:
                return ur.Quantity(value).to(self.to_unit)
            except DimensionalityError as e:
                raise FMValidationError(
                    f"Cannot convert value `{value}` to '{self.to_unit}'"
                ) from e
        else:
            raise FMValidationError(
                f"Unsupported value type. `{type(value)}` was provided but only dict and str are supported."
            )

    def _serialize(
        self, value: ur.Quantity | dict[str, Sensor], attr, data, **kwargs
    ) -> str | dict[str, int]:
        if isinstance(value, ur.Quantity):
            return str(value.to(self.to_unit))
        elif isinstance(value, Sensor):
            return dict(sensor=value.id)
        else:
            raise FMValidationError(
                "Serialized Quantity Or Sensor needs to be of type int, float or Sensor"
            )
