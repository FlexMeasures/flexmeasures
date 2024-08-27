from __future__ import annotations

import numbers

from flask import current_app
from marshmallow import (
    Schema,
    fields,
    validate,
    validates,
    ValidationError,
    validates_schema,
)
from marshmallow.validate import Validator

import json
import re
import isodate
import pandas as pd

from flexmeasures.data import ma, db
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.utils import (
    FMValidationError,
    MarshmallowClickMixin,
    with_appcontext_if_needed,
    convert_to_quantity,
)
from flexmeasures.utils.unit_utils import (
    is_valid_unit,
    ur,
    units_are_convertible,
)
from flexmeasures.data.schemas.times import DurationField, AwareDateTimeField
from flexmeasures.data.schemas.units import QuantityField


class JSON(fields.Field):
    def _deserialize(self, value, attr, data, **kwargs) -> dict:
        try:
            return json.loads(value)
        except ValueError:
            raise ValidationError("Not a valid JSON string.")

    def _serialize(self, value, attr, data, **kwargs) -> str:
        return json.dumps(value)


class TimedEventSchema(Schema):
    value = QuantityField(
        required=True,
        to_unit="dimensionless",  # placeholder, overridden in __init__
        default_src_unit="dimensionless",  # placeholder, overridden in __init__
        return_magnitude=True,  # placeholder, overridden in __init__
    )
    datetime = AwareDateTimeField(required=False)
    start = AwareDateTimeField(required=False)
    end = AwareDateTimeField(required=False)
    duration = DurationField(required=False)

    def __init__(
        self,
        timezone: str | None = None,
        value_validator: Validator | None = None,
        to_unit: str | None = None,
        default_src_unit: str | None = None,
        return_magnitude: bool = True,
        *args,
        **kwargs,
    ):
        """A time period (or single point) with a value.

        :param timezone:  Optionally, set a timezone to be able to interpret nominal durations.
        """
        self.timezone = timezone
        self.value_validator = value_validator
        super().__init__(*args, **kwargs)
        if to_unit is not None:
            if to_unit.startswith("/"):
                if len(to_unit) < 2:
                    raise ValueError(
                        f"Variable `to_unit='{to_unit}'` must define a denominator."
                    )
            setattr(self.fields["value"], "to_unit", to_unit)
        if default_src_unit is not None:
            setattr(self.fields["value"], "default_src_unit", default_src_unit)
        setattr(self.fields["value"], "return_magnitude", return_magnitude)

    @validates("value")
    def validate_value(self, _value):
        if self.value_validator is not None:
            self.value_validator(_value)

    @validates_schema
    def check_time_window(self, data: dict, **kwargs):
        """Checks whether a complete time interval can be derived from the timing fields.

        The data is updated in-place, guaranteeing that the 'start' and 'end' fields are filled out.
        """
        dt = data.get("datetime")
        start = data.get("start")
        end = data.get("end")
        duration = data.get("duration")

        if dt is not None:
            if any([p is not None for p in (start, end, duration)]):
                raise ValidationError(
                    "If using the 'datetime' field, no 'start', 'end' or 'duration' is expected."
                )
            data["start"] = dt
            data["end"] = dt
        elif duration is not None:
            if self.timezone is None and isinstance(duration, isodate.Duration):
                raise ValidationError(
                    "Cannot interpret nominal duration used in the 'duration' field without a known timezone."
                )
            elif all([p is None for p in (start, end)]) or all(
                [p is not None for p in (start, end)]
            ):
                raise ValidationError(
                    "If using the 'duration' field, either 'start' or 'end' is expected."
                )
            if start is not None:
                grounded = DurationField.ground_from(
                    duration, pd.Timestamp(start).tz_convert(self.timezone)
                )
                data["start"] = start
                data["end"] = start + grounded
            else:
                grounded = DurationField.ground_from(
                    -duration, pd.Timestamp(end).tz_convert(self.timezone)
                )
                data["start"] = end + grounded
                data["end"] = end
        else:
            if any([p is None for p in (start, end)]):
                raise ValidationError(
                    "Missing field(s) to describe timing: use the 'datetime' field, "
                    "or a combination of 2 fields of 'start', 'end' and 'duration'."
                )
            data["start"] = start
            data["end"] = end


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
        generic_asset = db.session.get(GenericAsset, generic_asset_id)
        if not generic_asset:
            raise ValidationError(
                f"Generic asset with id {generic_asset_id} doesn't exist."
            )
        # Add it to context to use it for AssetAuditLog record
        self.context["generic_asset"] = generic_asset

    class Meta:
        model = Sensor


class SensorIdField(MarshmallowClickMixin, fields.Int):
    """Field that deserializes to a Sensor and serializes back to an integer."""

    def __init__(self, *args, unit: str | ur.Quantity | None = None, **kwargs):
        super().__init__(*args, **kwargs)

        if isinstance(unit, str):
            self.to_unit = ur.Quantity(unit)
        elif isinstance(unit, ur.Quantity):
            self.to_unit = unit
        else:
            self.to_unit = None

    @with_appcontext_if_needed()
    def _deserialize(self, value: int, attr, obj, **kwargs) -> Sensor:
        """Turn a sensor id into a Sensor."""
        sensor = db.session.get(Sensor, value)
        if sensor is None:
            raise FMValidationError(f"No sensor found with id {value}.")

        # lazy loading now (sensor is somehow not in session after this)
        sensor.generic_asset
        sensor.generic_asset.generic_asset_type

        # if the units are defined, check if the sensor data is convertible to the target units
        if self.to_unit is not None and not units_are_convertible(
            sensor.unit, str(self.to_unit.units)
        ):
            raise FMValidationError(
                f"Cannot convert {sensor.unit} to {self.to_unit.units}"
            )

        return sensor

    def _serialize(self, sensor: Sensor, attr, data, **kwargs) -> int:
        """Turn a Sensor into a sensor id."""
        return sensor.id


class VariableQuantityField(MarshmallowClickMixin, fields.Field):
    def __init__(
        self,
        to_unit,
        *args,
        default_src_unit: str | None = None,
        return_magnitude: bool = False,
        timezone: str | None = None,
        value_validator: Validator | None = None,
        **kwargs,
    ):
        """Field for validating, serializing and deserializing a variable quantity.

        A variable quantity can be represented by a sensor, time series or fixed quantity.

        # todo: Sensor should perhaps deserialize already to sensor data

        NB any validators passed are only applied to Quantities.
        For example, validate=validate.Range(min=0) will raise a ValidationError in case of negative quantities,
        but will let pass any sensor that has recorded negative values.

        :param to_unit:             Unit to which the sensor, time series or quantity should be convertible.
                                    - Sensors are checked for convertibility, but the original sensor is returned,
                                      so its values are not yet converted.
                                    - Time series and quantities are already converted to the given unit.
                                    - Units starting with '/' (e.g. '/MWh') lead to accepting any value, which will be
                                      converted to the given unit. For example,
                                      a quantity of 1 EUR/kWh with to_unit='/MWh' is deserialized to 1000 EUR/MWh.
        :param default_src_unit:    What unit to use in case of getting a numeric value.
                                    Does not apply to time series or sensors.
        :param return_magnitude:    In case of getting a time series, whether the result should include
                                    the magnitude of each quantity, or each Quantity object itself.
        :param timezone:            Only used in case a time series is specified and one of the *timed events*
                                    in the time series uses a nominal duration, such as "P1D".
        """
        _validate = kwargs.pop("validate", None)
        super().__init__(*args, **kwargs)
        if _validate is not None:
            # Insert validation into self.validators so that multiple errors can be stored.
            validator = RepurposeValidatorToIgnoreSensors(_validate)
            self.validators.insert(0, validator)
        self.timezone = timezone
        self.value_validator = value_validator
        if to_unit.startswith("/") and len(to_unit) < 2:
            raise ValueError(
                f"Variable `to_unit='{to_unit}'` must define a denominator."
            )
        self.to_unit = to_unit
        self.default_src_unit = default_src_unit
        self.return_magnitude = return_magnitude

    @with_appcontext_if_needed()
    def _deserialize(
        self, value: dict[str, int] | list[dict] | str, attr, obj, **kwargs
    ) -> Sensor | list[dict] | ur.Quantity:

        if isinstance(value, dict):
            return self._deserialize_dict(value)
        elif isinstance(value, list):
            return self._deserialize_list(value)
        elif isinstance(value, str):
            return self._deserialize_str(value)
        elif isinstance(value, numbers.Real) and self.default_src_unit is not None:
            return self._deserialize_numeric(value, attr, obj, **kwargs)
        else:
            raise FMValidationError(
                f"Unsupported value type. `{type(value)}` was provided but only dict, list and str are supported."
            )

    def _deserialize_dict(self, value: dict[str, int]) -> Sensor:
        """Deserialize a sensor reference to a Sensor."""
        if "sensor" not in value:
            raise FMValidationError("Dictionary provided but `sensor` key not found.")
        sensor = SensorIdField(
            unit=self.to_unit if not self.to_unit.startswith("/") else None
        ).deserialize(value["sensor"], None, None)
        return sensor

    def _deserialize_list(self, value: list[dict]) -> list[dict]:
        """Deserialize a time series to a list of timed events."""
        if self.return_magnitude is True:
            current_app.logger.warning(
                "Deserialized time series will include Quantity objects in the future. Set `return_magnitude=False` to trigger the new behaviour."
            )
        field = fields.List(
            fields.Nested(
                TimedEventSchema(
                    timezone=self.timezone,
                    value_validator=self.value_validator,
                    to_unit=self.to_unit,
                    default_src_unit=self.default_src_unit,
                    return_magnitude=self.return_magnitude,
                )
            )
        )
        return field._deserialize(value, None, None)

    def _deserialize_str(self, value: str) -> ur.Quantity:
        """Deserialize a string to a Quantity."""
        return convert_to_quantity(value=value, to_unit=self.to_unit)

    def _deserialize_numeric(
        self, value: numbers.Real, attr, obj, **kwargs
    ) -> ur.Quantity:
        """Try to deserialize a numeric value to a Quantity, using the default_src_unit."""
        return self._deserialize(
            f"{value} {self.default_src_unit}", attr, obj, **kwargs
        )

    def _serialize(
        self, value: Sensor | pd.Series | ur.Quantity, attr, data, **kwargs
    ) -> str | dict[str, int]:
        if isinstance(value, Sensor):
            return dict(sensor=value.id)
        elif isinstance(value, pd.Series):
            raise NotImplementedError(
                "Serialization of a time series from a Pandas Series is not implemented yet."
            )
        elif isinstance(value, ur.Quantity):
            return str(value.to(self.to_unit))
        else:
            raise FMValidationError(
                "Serialized quantity, sensor or time series needs to be of type int, float, Sensor or pandas.Series."
            )

    def convert(self, value, param, ctx, **kwargs):
        # case that the click default is defined in numeric values
        if not isinstance(value, str):
            return super().convert(value, param, ctx, **kwargs)

        _value = re.match(r"sensor:(\d+)", value)

        if _value is not None:
            _value = {"sensor": int(_value.groups()[0])}
        else:
            _value = value

        return super().convert(_value, param, ctx, **kwargs)


class RepurposeValidatorToIgnoreSensors(validate.Validator):
    """Validator that executes another validator (the one you initialize it with) only on non-Sensor values."""

    def __init__(self, original_validator, *, error: str | None = None):
        self.error = error
        self.original_validator = original_validator

    def __call__(self, value):
        if not isinstance(value, Sensor):
            self.original_validator(value)
        return value


class QuantityOrSensor(VariableQuantityField):
    def __init__(self, *args, **kwargs):
        """Deprecated class. Use `VariableQuantityField` instead."""
        current_app.logger.warning(
            "Class `TimeSeriesOrSensor` is deprecated. Use `VariableQuantityField` instead."
        )
        super().__init__(return_magnitude=False, *args, **kwargs)


class TimeSeriesOrSensor(VariableQuantityField):
    def __init__(self, *args, **kwargs):
        """Deprecated class. Use `VariableQuantityField` instead."""
        current_app.logger.warning(
            "Class `TimeSeriesOrSensor` is deprecated. Use `VariableQuantityField` instead."
        )
        super().__init__(return_magnitude=True, *args, **kwargs)
