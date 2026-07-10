from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from difflib import get_close_matches
import numbers
import pytz
from pytz.exceptions import UnknownTimeZoneError
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flexmeasures.data.models.data_sources import DataSource

from flask import current_app
from flask_security import current_user
from marshmallow import (
    Schema,
    ValidationError,
    fields,
    post_load,
    pre_load,
    validates,
    validates_schema,
)
import marshmallow.validate as validate
from pandas.api.types import is_numeric_dtype
from pint.errors import PintError
import timely_beliefs as tb
from werkzeug.datastructures import FileStorage
from marshmallow.validate import Validator

import re
import isodate
from marshmallow_oneofschema import OneOfSchema
import pandas as pd

from flexmeasures.data import ma, db
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import Account, User
from flexmeasures.data.schemas.utils import (
    FMValidationError,
    MarshmallowClickMixin,
    with_appcontext_if_needed,
    convert_to_quantity,
)
from flexmeasures.data.services.data_sources import get_or_create_source
from flexmeasures.utils.time_utils import get_timezone
from flexmeasures.utils.unit_utils import (
    is_valid_unit,
    ur,
    units_are_convertible,
    convert_units,
    is_currency_unit,
    is_energy_unit,
)
from flexmeasures.data.schemas.attributes import JSON
from flexmeasures.data.schemas.times import DurationField, AwareDateTimeField
from flexmeasures.data.schemas.units import QuantityField
from flexmeasures.data.schemas.account import AccountIdField
from flexmeasures.data.schemas.sources import DataSourceIdField


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
        event_resolution: timedelta | None = None,
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
        self.event_resolution = event_resolution
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
    def validate_value(self, _value, **kwargs):
        if self.value_validator is not None:
            self.value_validator(_value)

    def floor_timing_fields(self, data: dict) -> None:
        if self.event_resolution in (None, timedelta(0)):
            return

        for key in ("datetime", "start", "end"):
            if data.get(key) is not None:
                data[key] = (
                    pd.Timestamp(data[key]).floor(self.event_resolution).to_pydatetime()
                )

    @validates_schema
    def check_time_window(self, data, **kwargs):
        """Checks whether a complete time interval can be derived from the timing fields.

        The data is updated in-place, guaranteeing that the 'start' and 'end' fields are filled out.
        """
        self.floor_timing_fields(data)
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
                try:
                    grounded = DurationField.ground_from(
                        duration, pd.Timestamp(start).tz_convert(self.timezone)
                    )
                except UnknownTimeZoneError:
                    grounded = DurationField.ground_from(duration, pd.Timestamp(start))
                data["start"] = start
                data["end"] = start + grounded
            else:
                try:
                    grounded = DurationField.ground_from(
                        -duration, pd.Timestamp(end).tz_convert(self.timezone)
                    )
                except UnknownTimeZoneError:
                    grounded = DurationField.ground_from(-duration, pd.Timestamp(end))
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

    id = ma.auto_field(
        dump_only=True,
        metadata=dict(
            description="The sensor's ID, which is automatically assigned.",
            example=5,
        ),
    )
    name = ma.auto_field(
        required=True, metadata=dict(description="The sensor's name.", example="power")
    )
    unit = ma.auto_field(
        required=True,
        metadata=dict(
            description="The sensor's (physical or economical) unit. Supports [<abbr title='International System of Units'>SI</abbr> units](https://en.wikipedia.org/wiki/International_System_of_Units) and [currency codes](https://en.wikipedia.org/wiki/ISO_4217).",
            example="EUR/kWh",
        ),
    )

    def timezone_validator(value: str):
        """Validate timezone, suggesting the closest match if possible or the server default otherwise."""
        if value not in pytz.all_timezones:
            suggestion = get_close_matches(value, pytz.all_timezones, n=1, cutoff=0.6)
            if suggestion:
                raise ValidationError(
                    f"Invalid timezone '{value}'. Did you mean '{suggestion[0]}'?"
                )
            raise ValidationError(
                f"Invalid timezone '{value}'. Example: {get_timezone()}."
            )

    timezone = ma.auto_field(
        validate=timezone_validator,
        metadata=dict(
            description="The sensor's [<abbr title='Internet Assigned Numbers Authority'>IANA</abbr> timezone](https://en.wikipedia.org/wiki/Tz_database). When getting sensor data out of the platform, you'll notice that the timezone offsets of datetimes correspond to this timezone, and includes offset changes due to <abbr title='Daylight Saving Time'>DST</abbr> transitions.",
            example="Europe/Amsterdam",
            enum=pytz.common_timezones,
        ),
    )
    event_resolution = DurationField(
        required=True,
        metadata=dict(
            description="The duration of events recorded by the sensor.",
            example="PT15M",
        ),
    )
    entity_address = fields.String(
        dump_only=True,
        metadata=dict(
            description="Obsolete identifier from [<abbr title='Universal Smart Energy Framework'>USEF</abbr>](https://www.usef.energy/).",
        ),
    )
    attributes = JSON(
        required=False,
        metadata=dict(
            description=(
                "JSON serializable attributes to store arbitrary information on "
                "the sensor. A few attributes lead to special behaviour, such as "
                "`consumption_is_positive`, which informs the platform whether "
                "consumption values should be saved (and shown in charts) as "
                "positive or negative values, `floor_datetimes_to_resolution`, "
                "which controls whether off-clock datetimes are floored to a "
                "non-instantaneous sensor's resolution, and `frequency`, which "
                "rounds incoming instantaneous measurements to a configured "
                "Pandas frequency."
            ),
            example='{"consumption_is_positive": true, "floor_datetimes_to_resolution": true}',
        ),
    )

    @validates("unit")
    def validate_unit(self, unit: str, **kwargs):
        if not is_valid_unit(unit):
            raise ValidationError(f"Unit '{unit}' cannot be handled.")

    @pre_load
    def set_default_timezone(self, data, **kwargs):
        """Set the default timezone to the server timezone only for a full load (POST, not PATCH)."""
        partial = kwargs.get("partial", False)
        if not partial and not data.get("timezone"):
            data["timezone"] = str(get_timezone())
        return data


class SensorSchema(SensorSchemaMixin, ma.SQLAlchemySchema):
    """
    Sensor schema with validations.
    """

    generic_asset_id = fields.Integer(
        required=True,
        metadata=dict(description="The asset that the sensor belongs to.", example=1),
    )

    @validates("generic_asset_id")
    def validate_generic_asset(self, generic_asset_id: int, **kwargs):
        generic_asset = db.session.get(GenericAsset, generic_asset_id)
        if not generic_asset:
            raise ValidationError(
                f"Generic asset with id {generic_asset_id} doesn't exist."
            )

    class Meta:
        model = Sensor


class SensorIdField(MarshmallowClickMixin, fields.Int):
    """Field that deserializes to a Sensor and serializes back to an integer."""

    def __init__(
        self,
        asset: GenericAsset | None = None,
        unit: str | ur.Quantity | None = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.asset = asset

        if isinstance(unit, str):
            self.to_unit = ur.Quantity(unit)
        elif isinstance(unit, ur.Quantity):
            self.to_unit = unit
        else:
            self.to_unit = None

    @with_appcontext_if_needed()
    def _deserialize(self, value: Any, attr, data, **kwargs) -> Sensor:
        """Turn a sensor id into a Sensor."""

        if not isinstance(value, int) and not isinstance(value, str):
            raise FMValidationError(
                f"Sensor ID has the wrong type. Got `{type(value).__name__}` but `int` was expected."
            )
        sensor_id: int = super()._deserialize(value, attr, data, **kwargs)

        sensor = db.session.get(Sensor, sensor_id)

        if sensor is None:
            raise FMValidationError(f"No sensor found with ID {sensor_id}.")

        # lazy loading now (sensor is somehow not in session after this)
        sensor.generic_asset
        sensor.generic_asset.generic_asset_type

        # if the asset is defined, check if the sensor belongs to it (or to its offspring)
        if (
            self.asset is not None
            and sensor.generic_asset != self.asset
            and sensor.generic_asset not in self.asset.offspring
        ):
            raise FMValidationError(
                f"Sensor {value} must be assigned to asset {self.asset} (or to one of its offspring)"
            )

        # if the units are defined, check if the sensor data is convertible to the target units
        if self.to_unit is not None and not units_are_convertible(
            sensor.unit, str(self.to_unit.units)
        ):
            raise FMValidationError(
                f"Cannot convert {sensor.unit} to {self.to_unit.units}"
            )

        return sensor

    def _serialize(self, value: Sensor, attr, obj, **kwargs) -> int:
        """Turn a Sensor into a sensor id."""
        return value.id


class VariableQuantityField(MarshmallowClickMixin, fields.Field):
    _UNSUPPORTED_VALUE_TYPE_MESSAGE = (
        "Unsupported value type. `{value_type}` was provided but only dict, list, "
        "str, pint Quantity, tuple, and numeric values with a default source unit are supported."
    )

    def __init__(
        self,
        to_unit,
        *args,
        default_src_unit: str | None = None,
        return_magnitude: bool = False,
        timezone: str | None = None,
        event_resolution: timedelta | None = None,
        value_validator: Validator | None = None,
        additional_sensor_units: list[str] | None = None,
        **kwargs,
    ):
        """Field for validating, serializing and deserializing a variable quantity.

        A variable quantity can be represented by a sensor, time series or fixed quantity.

        # todo: Sensor should perhaps deserialize already to sensor data

        NB any value validators passed are only applied to Quantities.
        For example, value_validator=validate.Range(min=0) will raise a ValidationError in case of negative quantities,
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
                                    In case to_unit is dimensionless, default_src_unit defaults to dimensionless;
                                    as a result, numeric values are accepted.
        :param return_magnitude:    In case of getting a time series, whether the result should include
                                    the magnitude of each quantity, or each Quantity object itself.
        :param timezone:            Only used in case a time series is specified and one of the *timed events*
                                    in the time series uses a nominal duration, such as "P1D".
        :param additional_sensor_units:
                                    Additional sensor units (besides those convertible to ``to_unit``) that are
                                    accepted for sensor references. Use this only for units that are dimensionally
                                    incompatible with ``to_unit`` but contextually meaningful — for example,
                                    ``["%"]`` allows sensors with a percentage unit for fields where the conversion
                                    requires an external capacity factor (such as ``soc-max``).
                                    The actual unit conversion must be handled downstream by the caller.
                                    Do not use this as a general-purpose unit allowlist.
        """
        super().__init__(*args, **kwargs)
        if value_validator is not None:
            # Insert validation into self.validators so that multiple errors can be stored.
            value_validator = RepurposeValidatorToIgnoreSensorsAndLists(value_validator)
            self.validators.insert(0, value_validator)
        self.timezone = timezone
        self.event_resolution = event_resolution
        self.value_validator = value_validator
        if to_unit.startswith("/") and len(to_unit) < 2:
            raise ValueError(
                f"Variable `to_unit='{to_unit}'` must define a denominator."
            )
        self.to_unit = to_unit
        if default_src_unit is None and units_are_convertible(
            self.to_unit, "dimensionless"
        ):
            default_src_unit = "dimensionless"
        self.default_src_unit = default_src_unit
        self.return_magnitude = return_magnitude
        self.additional_sensor_units = additional_sensor_units or []

    @with_appcontext_if_needed()
    def _deserialize(
        self,
        value: (
            dict[str, Any]
            | list[dict]
            | str
            | ur.Quantity
            | tuple[Any, ...]
            | numbers.Real
        ),
        attr,
        data,
        **kwargs,
    ) -> Sensor | SensorReference | list[dict] | ur.Quantity:

        if isinstance(value, dict):
            return self._deserialize_dict(value, attr, data, **kwargs)
        elif isinstance(value, list):
            return self._deserialize_list(value)
        elif isinstance(value, str):
            return self._deserialize_str(value)
        elif isinstance(value, ur.Quantity):
            return value.to(self.to_unit)
        elif isinstance(value, tuple):
            try:
                return ur.Quantity.from_tuple(value).to(self.to_unit)
            except (PintError, TypeError, ValueError, AttributeError, IndexError):
                if (
                    len(value) == 1
                    and isinstance(value[0], numbers.Real)
                    and self.default_src_unit is not None
                ):
                    return self._deserialize_numeric(value[0], attr, data, **kwargs)
                if len(value) == 2:
                    return self._deserialize_str(f"{value[0]} {value[1]}")
                raise FMValidationError(
                    self._UNSUPPORTED_VALUE_TYPE_MESSAGE.format(value_type=type(value))
                )
        elif isinstance(value, numbers.Real) and self.default_src_unit is not None:
            return self._deserialize_numeric(value, attr, data, **kwargs)
        else:
            raise FMValidationError(
                self._UNSUPPORTED_VALUE_TYPE_MESSAGE.format(value_type=type(value))
            )

    _SOURCE_FILTER_KEYS = frozenset(
        {"source-types", "exclude-source-types", "sources", "source-account"}
    )

    def _deserialize_source_filters(self, value: dict[str, Any]) -> tuple[
        list[str] | None,
        list[str] | None,
        list[DataSource] | None,
        list[Account] | None,
    ]:
        """Deserialize and validate source filter fields from a sensor-reference dict.

        Returns ``(source_types, exclude_source_types, sources, source_account)``.
        """
        source_types = value.get("source-types")
        if source_types is not None:
            if not isinstance(source_types, list) or not all(
                isinstance(s, str) for s in source_types
            ):
                raise FMValidationError("`source-types` must be a list of strings.")

        exclude_source_types = value.get("exclude-source-types")
        if exclude_source_types is not None:
            if not isinstance(exclude_source_types, list) or not all(
                isinstance(s, str) for s in exclude_source_types
            ):
                raise FMValidationError(
                    "`exclude-source-types` must be a list of strings."
                )

        sources = None
        raw_sources = value.get("sources")
        if raw_sources is not None:
            if not isinstance(raw_sources, list):
                raise FMValidationError("`sources` must be a list of data source IDs.")
            source_id_field = DataSourceIdField()
            sources = [
                source_id_field.deserialize(src_id, None, None)
                for src_id in raw_sources
            ]

        source_account = None
        raw_source_account = value.get("source-account")
        if raw_source_account is not None:
            if not isinstance(raw_source_account, list):
                raise FMValidationError(
                    "`source-account` must be a list of account IDs."
                )
            account_id_field = AccountIdField()
            source_account = [
                account_id_field.deserialize(acc_id, None, None)
                for acc_id in raw_source_account
            ]

        return source_types, exclude_source_types, sources, source_account

    def _deserialize_dict(
        self, value: dict[str, Any], attr, data, **kwargs
    ) -> Sensor | SensorReference:
        """Deserialize a sensor reference to a Sensor or SensorReference.

        Returns a plain :class:`Sensor` when no source filter or default keys are
        present (backward compatible), and a :class:`SensorReference` when any of
        ``source-types``, ``exclude-source-types``, ``sources``, ``source-account``
        or ``default`` are provided.
        """
        if "sensor" not in value:
            raise FMValidationError("Dictionary provided but `sensor` key not found.")
        if self.additional_sensor_units:
            # With additional allowed units, bypass the built-in unit check and perform our own
            sensor = SensorIdField(unit=None).deserialize(value["sensor"], None, None)
            if self.to_unit and not self.to_unit.startswith("/"):
                if (
                    not units_are_convertible(sensor.unit, self.to_unit)
                    and sensor.unit not in self.additional_sensor_units
                ):
                    raise FMValidationError(
                        f"Cannot convert {sensor.unit} to {self.to_unit}"
                    )
        else:
            sensor = SensorIdField(
                unit=self.to_unit if not self.to_unit.startswith("/") else None
            ).deserialize(value["sensor"], None, None)

        default = None
        if "default" in value:
            default = self._deserialize_default(value["default"], attr, data, **kwargs)

        # If no source filter or default keys are present, keep returning a plain Sensor.
        if self._SOURCE_FILTER_KEYS.isdisjoint(value.keys()) and default is None:
            return sensor  # backward compat: no filters → plain Sensor

        source_types, exclude_source_types, sources, source_account = (
            self._deserialize_source_filters(value)
        )
        return SensorReference(
            sensor=sensor,
            source_types=source_types,
            exclude_source_types=exclude_source_types,
            sources=sources,
            source_account=source_account,
            default=default,
        )

    def _deserialize_default(self, value, attr, data, **kwargs) -> ur.Quantity:
        """Deserialize a sensor reference fallback value."""
        if isinstance(value, str):
            default = self._deserialize_str(value)
        elif isinstance(value, numbers.Real) and self.default_src_unit is not None:
            default = self._deserialize_numeric(value, attr, data, **kwargs)
        else:
            raise FMValidationError(
                "Sensor reference `default` must be a quantity string or a numeric value with a known default source unit."
            )
        if self.value_validator is not None:
            self.value_validator(default)
        return default

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
                    event_resolution=self.event_resolution,
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
        self, value: numbers.Real, attr, data, **kwargs
    ) -> ur.Quantity:
        """Try to deserialize a numeric value to a Quantity, using the default_src_unit."""
        return self._deserialize(
            f"{value} {self.default_src_unit}", attr, data, **kwargs
        )

    def _serialize(
        self,
        value: Sensor | SensorReference | pd.Series | ur.Quantity,
        attr,
        obj,
        **kwargs,
    ) -> str | dict[str, Any]:
        if isinstance(value, SensorReference):
            sensor_reference: dict[str, Any] = dict(sensor=value.id)
            if value.source_types is not None:
                sensor_reference["source-types"] = value.source_types
            if value.exclude_source_types is not None:
                sensor_reference["exclude-source-types"] = value.exclude_source_types
            if value.sources is not None:
                sensor_reference["sources"] = [source.id for source in value.sources]
            if value.source_account is not None:
                sensor_reference["source-account"] = [
                    account.id for account in value.source_account
                ]
            if value.default is not None:
                sensor_reference["default"] = str(value.default.to(self.to_unit))
            return sensor_reference
        elif isinstance(value, Sensor):
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

    def _get_original_unit(
        self,
        serialized_variable_quantity: str | list[dict] | dict,
        deserialized_variable_quantity: (
            ur.Quantity | list[dict] | Sensor | SensorReference
        ),
    ) -> str:
        """Obtain the original unit from the still serialized variable quantity."""
        if isinstance(serialized_variable_quantity, str):
            unit = str(ur.Quantity(serialized_variable_quantity).units)
        elif isinstance(serialized_variable_quantity, list):
            unit = str(ur.Quantity(serialized_variable_quantity[0]["value"]).units)
        elif isinstance(serialized_variable_quantity, dict):
            # use deserialized quantity to avoid another Sensor query; the serialized quantity only has the sensor ID
            assert isinstance(deserialized_variable_quantity, (Sensor, SensorReference))
            unit = deserialized_variable_quantity.unit
        else:
            raise NotImplementedError(
                f"Unexpected type '{type(serialized_variable_quantity)}' for serialized_variable_quantity describing '{self.data_key}': {serialized_variable_quantity}."
            )
        return unit

    def _get_unit(
        self, variable_quantity: ur.Quantity | list[dict] | Sensor | SensorReference
    ) -> str:
        """Obtain the unit from the (deserialized) variable quantity.

        >>> VariableQuantityField("MW")._get_unit(ur.Quantity("3 kWh"))
        'kWh'
        >>> VariableQuantityField("/MW")._get_unit([{'value': ur.Quantity("3 kEUR/MWh")}, {'value': ur.Quantity("0 EUR/kWh")}])
        'kEUR/MWh'
        """
        if isinstance(variable_quantity, ur.Quantity):
            unit = str(variable_quantity.units)
        elif isinstance(variable_quantity, list):
            unit = str(variable_quantity[0]["value"].units)
            if not all(
                units_are_convertible(
                    from_unit=str(variable_quantity[j]["value"].units),
                    to_unit=unit,
                    duration_known=False,  # prevent mistakes by not allowing to mix kW and kWh units within a single time series specification
                )
                for j in range(len(variable_quantity))
            ):
                raise ValidationError(
                    "Segments of a time series must share the same unit.",
                    field_name=self.data_key,
                )
        elif isinstance(variable_quantity, (Sensor, SensorReference)):
            unit = variable_quantity.unit
        else:
            raise NotImplementedError(
                f"Unexpected type '{type(variable_quantity)}' for variable_quantity describing '{self.data_key}': {variable_quantity}."
            )
        return unit


class RepurposeValidatorToIgnoreSensorsAndLists(validate.Validator):
    """Validator that executes another validator (the one you initialize it with) only on non-Sensor and non-list values."""

    def __init__(self, original_validator, *, error: str | None = None):
        self.error = error
        self.original_validator = original_validator

    def __call__(self, value):
        if not isinstance(value, (Sensor, SensorReference, list)):
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


class SensorDataFileDescriptionSchema(Schema):
    """
    Schema for uploading a file with sensor data.
    This one describes only the file upload part, not the sensor itself.
    See SensorDataFileSchema for the full schema.
    """

    uploaded_files = fields.List(
        fields.Raw(metadata={"type": "file"}),
        data_key="uploaded-files",
    )
    belief_time_measured_instantly = fields.Boolean(
        metadata={"type": "boolean", "default": False},
        required=False,
        allow_none=True,
        truthy={"on", "true", "True", "1"},
        falsy={"off", "false", "False", "0", None},
        data_key="belief-time-measured-instantly",
    )
    unit = fields.String(
        required=False,
        data_key="unit",
    )


class SensorDataFileSchema(SensorDataFileDescriptionSchema):
    sensor = SensorIdField(data_key="id")

    def __init__(self, *args, source_user: User | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_user = source_user

    _valid_content_types = {
        "text/csv",
        "text/plain",
        "text/x-csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }

    @validates("uploaded_files")
    def validate_uploaded_files(self, files: list[FileStorage], **kwargs):
        """Validate the deserialized fields."""
        errors = {}
        for i, file in enumerate(files):
            file_errors = []
            if not isinstance(file, FileStorage):
                file_errors += [
                    f"Invalid content: {file}. Only CSV files are accepted."
                ]
            if not file.filename:
                file_errors += ["Filename is missing."]
            elif file.filename.split(".")[-1] not in (
                "csv",
                "CSV",
                "xlsx",
                "XLSX",
                "xls",
                "XLS",
                "xlsm",
                "XLSM",
            ):
                file_errors += [
                    f"Invalid filename: {file.filename}. Only CSV or Excel files are accepted."
                ]
            if file.content_type not in self._valid_content_types:
                file_errors += [
                    f"Invalid content type: {file.content_type}. Only the following content types are accepted: {self._valid_content_types}."
                ]
            if file_errors:
                errors[i] = file_errors
        if errors:
            raise ValidationError(errors)

    @validates_schema
    def validate_unit(self, data, **kwargs):
        """Validate unit compatibility with the sensor's unit."""
        unit = data.get("unit")
        sensor: Sensor = data.get("sensor")

        if unit is not None:
            if not units_are_convertible(unit, sensor.unit):
                raise ValidationError(
                    field="unit",
                    message=f"Provided unit '{unit}' is not convertible to sensor unit '{sensor.unit}'",
                )

    @post_load
    def post_load(self, fields, **kwargs):
        """Process the deserialized and validated fields.
        Remove the 'sensor' and 'files' fields, and add the 'data' field containing a list of BeliefsDataFrames.
        """
        sensor = fields.pop("sensor")
        dfs = []
        files: list[FileStorage] = fields.pop("uploaded_files")
        belief_time_measured_instantly = fields.pop("belief_time_measured_instantly")

        errors = {}
        for i, file in enumerate(files):
            try:
                bdf = tb.read_csv(
                    file,
                    sensor,
                    source=get_or_create_source(self.source_user or current_user),
                    belief_time=(
                        pd.Timestamp.utcnow()
                        if not belief_time_measured_instantly
                        else None
                    ),
                    belief_horizon=(
                        pd.Timedelta(days=0) if belief_time_measured_instantly else None
                    ),
                    resample=False,
                    timezone=sensor.timezone,
                )
                assert is_numeric_dtype(
                    bdf["event_value"]
                ), "event values should be numeric"

                from_unit = fields.get("unit", sensor.unit)

                # Start to infer the event resolution
                if len(bdf) == 1:
                    bdf.event_resolution = sensor.event_resolution
                elif len(bdf) == 2:
                    # Pandas cannot infer an event frequency, but we can (try)
                    bdf.event_resolution = abs(
                        bdf.event_starts[-1] - bdf.event_starts[0]
                    )
                else:
                    bdf.event_resolution = bdf.most_common_event_frequency
                if bdf.event_resolution is None:
                    # Reraise the error if an event frequency could not be inferred
                    pd.infer_freq(bdf.index.unique("event_start"))

                if sensor.event_resolution != timedelta(0) and sensor.get_attribute(
                    "floor_datetimes_to_resolution", True
                ):
                    bdf = floor_bdf_event_starts(bdf, bdf.event_resolution)

                bdf["event_value"] = convert_units(
                    bdf["event_value"],
                    from_unit,
                    sensor.unit,
                    # todo: remove the next line when https://github.com/SeitaBV/timely-beliefs/issues/220 is fixed
                    event_resolution=bdf.event_resolution,
                )

                if sensor.event_resolution != timedelta(0):

                    # Special cases for resampling known stock units
                    # todo: allow users to override this behaviour
                    known_stock_unit_validators = [is_currency_unit, is_energy_unit]
                    if units_are_convertible(
                        from_unit, sensor.unit, duration_known=False
                    ) and any(
                        is_stock_unit(from_unit)
                        for is_stock_unit in known_stock_unit_validators
                    ):
                        bdf = bdf.resample_events(
                            sensor.event_resolution,
                            method="sum",
                            keep_only_most_recent_belief=True,
                        )
                    else:
                        bdf = bdf.resample_events(
                            sensor.event_resolution,
                            keep_only_most_recent_belief=True,
                        )
                dfs.append(bdf)
            except Exception as e:
                error_message = (
                    f"Invalid content in file: {file.filename}. Failed with: {str(e)}"
                )
                current_app.logger.info(
                    f"Upload failed for sensor {sensor.id}. {error_message}"
                )
                errors[i] = error_message
        if errors:
            raise ValidationError(errors)
        fields["data"] = dfs
        fields["filenames"] = [file.filename for file in files]
        return fields


def floor_bdf_event_starts(
    bdf: tb.BeliefsDataFrame, event_resolution: timedelta
) -> tb.BeliefsDataFrame:
    floored_event_starts = bdf.index.get_level_values("event_start").floor(
        event_resolution
    )

    new_index = pd.MultiIndex.from_arrays(
        [
            (
                floored_event_starts
                if name == "event_start"
                else bdf.index.get_level_values(name)
            )
            for name in bdf.index.names
        ],
        names=bdf.index.names,
    )
    if new_index.duplicated().any():
        raise ValidationError(
            "Flooring event_start would merge multiple beliefs with the same "
            "source, belief_time and event_start. Please provide data already "
            "aligned to the event resolution or use distinct belief/source metadata."
        )

    floored_bdf = bdf.copy()
    floored_bdf.index = new_index
    return floored_bdf


class SensorDataFileRequestSchema(SensorDataFileSchema):
    """Validate a sensor data upload without parsing or resampling its files."""

    @post_load
    def post_load(self, fields, **kwargs):
        files: list[FileStorage] = fields["uploaded_files"]
        fields["filenames"] = [file.filename for file in files]
        return fields


class QuantitySchema(Schema):
    """Represents a quantity string like '1 EUR/MWh'."""

    quantity = fields.Str(
        required=True,
        metadata=dict(
            description="Quantity string describing a fixed quantity.",
            examples=["130 EUR/MWh", "12 V", "4.5 m/s", "20 °C", "3 * 230V * 16A"],
        ),
    )


@dataclass
class SensorReference:
    """A sensor reference that wraps a Sensor with optional query settings.

    Exposes the same ``unit``, ``id``, and ``event_resolution`` properties as a plain
    :class:`~flexmeasures.data.models.time_series.Sensor`, so code that reads those
    properties works without modification. The source filters and optional default
    value are passed through to
    :func:`~flexmeasures.data.models.planning.utils.get_series_from_quantity_or_sensor`.
    """

    sensor: Sensor
    source_types: list[str] | None = field(default=None)
    exclude_source_types: list[str] | None = field(default=None)
    sources: list[DataSource] | None = field(default=None)
    source_account: list[Account] | None = field(default=None)
    default: ur.Quantity | None = field(default=None)

    @property
    def unit(self) -> str:
        """Unit of the underlying sensor."""
        return self.sensor.unit

    @property
    def id(self) -> int:
        """ID of the underlying sensor."""
        return self.sensor.id

    @property
    def event_resolution(self) -> timedelta:
        """Event resolution of the underlying sensor."""
        return self.sensor.event_resolution


class SensorReferenceSchema(Schema):
    """Sensor reference with optional source filters and fallback value."""

    class Meta:
        description = "Sensor reference from which to look up a variable quantity."

    sensor = SensorIdField(
        required=True,
        metadata=dict(
            description="ID of the sensor on which the data is recorded.",
        ),
    )
    source_types = fields.List(
        fields.String(),
        load_default=None,
        data_key="source-types",
        metadata=dict(
            description="Only use beliefs from sources with these source types (e.g. 'user', 'script', 'forecaster', 'scheduler').",
        ),
    )
    exclude_source_types = fields.List(
        fields.String(),
        load_default=None,
        data_key="exclude-source-types",
        metadata=dict(
            description="Exclude beliefs from sources with these source types.",
        ),
    )
    sources = fields.List(
        DataSourceIdField(),
        load_default=None,
        metadata=dict(
            description="Only use beliefs from these data source IDs.",
        ),
    )
    source_account = fields.List(
        AccountIdField(),
        load_default=None,
        data_key="source-account",
        metadata=dict(
            description="Only use beliefs from data sources linked to these account IDs.",
        ),
    )
    default = fields.String(
        required=False,
        allow_none=False,
        metadata=dict(
            description="Fallback quantity to use when the referenced sensor has missing values.",
            example="0 kWh",
        ),
    )


class TimeSeriesSchema(Schema):
    """List of time series segments."""

    timeseries = fields.List(
        fields.Dict,
        required=True,
        metadata=dict(
            description=(
                "Time series specification containing a list of segments that together "
                "describe a variable quantity. Each segment may specify either "
                "`datetime`, `start` and `end`, `start` and `duration`, or `end` and "
                "`duration`."
            ),
            example=[
                {"value": "23 kW", "datetime": "2025-11-20T15:15+01"},
                {
                    "value": "24 kW",
                    "start": "2025-11-20T16:00+01",
                    "end": "2025-11-20T17:00+01",
                },
                {"value": "25 kW", "start": "2025-11-20T17:00+01", "duration": "PT1H"},
                {"value": "26 kW", "end": "2025-11-20T19:00+01", "duration": "PT1H"},
            ],
        ),
    )


class VariableQuantityOpenAPISchema(OneOfSchema):
    type_schemas = {
        "quantity_string": QuantitySchema,
        "sensor_reference": SensorReferenceSchema,
        "timeseries_specs": TimeSeriesSchema,
    }

    def get_obj_type(self, obj):
        # Required for OneOfSchema; not used during OpenAPI generation
        if isinstance(obj, dict) and "sensor" in obj:
            return "sensor_reference"
        if isinstance(obj, str):
            # Pretend incoming string maps to the string schema
            return "quantity_string"
        if isinstance(obj, list):
            return "timeseries_specs"
        return None
