from __future__ import annotations

from datetime import datetime, timedelta

from marshmallow import (
    Schema,
    fields,
    validate,
    validates_schema,
    ValidationError,
    pre_load,
    post_dump,
)
import pandas as pd

from flexmeasures import Asset, Sensor
from flexmeasures.data.schemas.generic_assets import GenericAssetIdField
from flexmeasures.data.schemas.sensors import (
    VariableQuantityField,
    SensorIdField,
)
from flexmeasures.data.schemas.utils import FMValidationError
from flexmeasures.data.schemas.times import AwareDateTimeField, PlanningDurationField
from flexmeasures.utils.flexmeasures_inflection import p
from flexmeasures.utils.unit_utils import (
    ur,
    units_are_convertible,
    is_capacity_price_unit,
    is_energy_price_unit,
    is_power_unit,
    is_energy_unit,
)


def series_range_validator(min=None, max=None):
    range_validator = validate.Range(min=min, max=max)

    def _validate_series(value):
        if isinstance(value, pd.Series):
            invalid_mask = pd.Series([False] * len(value), index=value.index)

            if min is not None:
                invalid_mask |= value < min
            if max is not None:
                invalid_mask |= value > max

            if invalid_mask.any():
                invalid_indexes = value.index[invalid_mask].tolist()
                invalid_values = value[invalid_mask].tolist()
                raise ValidationError(
                    f"Series contains values outside the allowed range (min={min}, max={max}).\n"
                    f"Invalid entries:\n"
                    f"Indexes: {invalid_indexes}\n"
                    f"Values: {invalid_values}"
                )
        else:
            range_validator(value)

    return _validate_series


class FlexContextSchema(Schema):
    """This schema defines fields that provide context to the portfolio to be optimized."""

    shared_currency_unit = fields.String(
        data_key="shared-currency-unit",
        required=False,
        load_default="EUR",
    )

    # Device commitments
    consumption_breach_price = VariableQuantityField(
        "/MW",
        data_key="consumption-breach-price",
        required=False,
        value_validator=series_range_validator(min=0),
        default=None,
        fill_sides=True,
    )
    production_breach_price = VariableQuantityField(
        "/MW",
        data_key="production-breach-price",
        required=False,
        value_validator=series_range_validator(min=0),
        default=None,
        fill_sides=True,
    )
    soc_minima_breach_price = VariableQuantityField(
        "/MWh",
        data_key="soc-minima-breach-price",
        required=False,
        value_validator=series_range_validator(min=0),
        default=None,
        add_resolution=True,
        fill_sides=True,
    )
    soc_maxima_breach_price = VariableQuantityField(
        "/MWh",
        data_key="soc-maxima-breach-price",
        required=False,
        value_validator=series_range_validator(min=0),
        default=None,
        add_resolution=True,
        fill_sides=True,
    )
    # Dev fields
    relax_soc_constraints = fields.Bool(
        data_key="relax-soc-constraints", load_default=False
    )
    relax_capacity_constraints = fields.Bool(
        data_key="relax-capacity-constraints", load_default=False
    )

    # Energy commitments
    ems_power_capacity_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-power-capacity",
        value_validator=series_range_validator(min=0),
        resolve_overlaps="min",
    )
    # todo: deprecated since flexmeasures==0.23
    consumption_price_sensor = SensorIdField(
        data_key="consumption-price-sensor", fill_sides=True
    )
    production_price_sensor = SensorIdField(
        data_key="production-price-sensor", fill_sides=True
    )
    consumption_price = VariableQuantityField(
        "/MWh",
        required=False,
        data_key="consumption-price",
        return_magnitude=False,
        fill_sides=True,
    )
    production_price = VariableQuantityField(
        "/MWh",
        required=False,
        data_key="production-price",
        return_magnitude=False,
        fill_sides=True,
    )

    # Capacity breach commitments
    ems_production_capacity_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-production-capacity",
        value_validator=series_range_validator(min=0),
        resolve_overlaps="min",
    )
    ems_consumption_capacity_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-consumption-capacity",
        value_validator=series_range_validator(min=0),
        resolve_overlaps="min",
    )
    ems_consumption_breach_price = VariableQuantityField(
        "/MW",
        data_key="site-consumption-breach-price",
        required=False,
        value_validator=series_range_validator(min=0),
        default=None,
        fill_sides=True,
    )
    ems_production_breach_price = VariableQuantityField(
        "/MW",
        data_key="site-production-breach-price",
        required=False,
        value_validator=series_range_validator(min=0),
        default=None,
        fill_sides=True,
    )

    # Peak consumption commitment
    ems_peak_consumption_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-peak-consumption",
        value_validator=series_range_validator(min=0),
        default="0 kW",
        fill_sides=True,
    )
    ems_peak_consumption_price = VariableQuantityField(
        "/MW",
        data_key="site-peak-consumption-price",
        required=False,
        value_validator=series_range_validator(min=0),
        default=None,
        fill_sides=True,
    )

    # Peak production commitment
    ems_peak_production_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-peak-production",
        value_validator=series_range_validator(min=0),
        default="0 kW",
        fill_sides=True,
    )
    ems_peak_production_price = VariableQuantityField(
        "/MW",
        data_key="site-peak-production-price",
        required=False,
        value_validator=series_range_validator(min=0),
        default=None,
        fill_sides=True,
    )
    # todo: group by month start (MS), something like a commitment resolution, or a list of datetimes representing splits of the commitments

    inflexible_device_sensors = fields.List(
        SensorIdField(), data_key="inflexible-device-sensors"
    )

    def __init__(
        self,
        asset: Asset | None = None,
        load_time_series: bool = False,
        query_window: tuple[datetime, datetime] | None = None,
        resolution: timedelta | None = None,
        belief_time: datetime | None = None,
        *args,
        **kwargs,
    ):
        if load_time_series and asset is None:
            raise NotImplementedError("Cannot load time series from an unknown asset.")
        self.asset = asset
        self.load_time_series = load_time_series
        self.query_window = query_window
        self.resolution = resolution
        self.belief_time = belief_time
        super().__init__(*args, **kwargs)

    def set_default_breach_prices(
        self, data: dict, fields: list[str], price: ur.Quantity
    ):
        """Fill in default breach prices.

        This relies on _try_to_convert_price_units to run first, setting a shared currency unit.
        """
        for field in fields:
            # use the same denominator as defined in the field
            data[field] = price.to(
                data["shared_currency_unit"]
                + "/"
                + self.declared_fields[field].to_unit.split("/")[-1]
            )
        return data

    @validates_schema
    def check_prices(self, data: dict, **kwargs):
        """Check assumptions about prices.

        1. The flex-context must contain at most 1 consumption price and at most 1 production price field.
        2. All prices must share the same currency.
        """
        if self.load_time_series:
            return data

        # The flex-context must contain at most 1 consumption price and at most 1 production price field
        if "consumption_price_sensor" in data and "consumption_price" in data:
            raise ValidationError(
                "Must pass either consumption-price or consumption-price-sensor."
            )
        if "production_price_sensor" in data and "production_price" in data:
            raise ValidationError(
                "Must pass either production-price or production-price-sensor."
            )

        # New price fields can only be used after updating to the new consumption-price and production-price fields
        field_map = {
            field.data_key: field_var
            for field_var, field in self.declared_fields.items()
        }
        if any(
            field_map[field] in data
            for field in (
                "soc-minima-breach-price",
                "soc-maxima-breach-price",
                "site-consumption-breach-price",
                "site-production-breach-price",
                "site-peak-consumption-price",
                "site-peak-production-price",
            )
        ):
            if field_map["consumption-price-sensor"] in data:
                raise ValidationError(
                    f"""Please switch to using `consumption-price: {{"sensor": {data[field_map["consumption-price-sensor"]].id}}}`."""
                )
            if field_map["production-price-sensor"] in data:
                raise ValidationError(
                    f"""Please switch to using `production-price: {{"sensor": {data[field_map["production-price-sensor"]].id}}}`."""
                )

        # make sure that the prices fields are valid price units

        # All prices must share the same unit
        data = self._try_to_convert_price_units(data)

        # Fill in default soc breach prices when asked to relax SoC constraints.
        if data["relax_soc_constraints"]:
            self.set_default_breach_prices(
                data,
                fields=["soc_minima_breach_price", "soc_maxima_breach_price"],
                price=ur.Quantity("1000 EUR/kWh"),
            )

        # Fill in default capacity breach prices when asked to relax capacity constraints.
        if data["relax_capacity_constraints"]:
            self.set_default_breach_prices(
                data,
                fields=["consumption_breach_price", "production_breach_price"],
                price=ur.Quantity("100 EUR/kW"),
            )

        return data

    def _try_to_convert_price_units(self, data):
        """Convert price units to the same unit and scale if they can (incl. same currency)."""

        shared_currency_unit = None
        previous_field_name = None
        for field in self.declared_fields:
            if field[-5:] == "price" and field in data:
                price_field = self.declared_fields[field]
                price_unit = price_field._get_unit(data[field])
                currency_unit = str(
                    (
                        ur.Quantity(price_unit) / ur.Quantity(f"1{price_field.to_unit}")
                    ).units
                )

                if shared_currency_unit is None:
                    shared_currency_unit = str(
                        ur.Quantity(currency_unit).to_base_units().units
                    )
                    previous_field_name = price_field.data_key
                if units_are_convertible(currency_unit, shared_currency_unit):
                    # Make sure all compatible currency units are on the same scale (e.g. not kEUR mixed with EUR)
                    if currency_unit != shared_currency_unit:
                        denominator_unit = str(
                            ur.Unit(currency_unit) / ur.Unit(price_unit)
                        )
                        if isinstance(data[field], ur.Quantity):
                            data[field] = data[field].to(
                                f"{shared_currency_unit}/({denominator_unit})"
                            )
                        elif isinstance(data[field], list):
                            for j in range(len(data[field])):
                                data[field][j]["value"] = data[field][j]["value"].to(
                                    f"{shared_currency_unit}/({denominator_unit})"
                                )
                        elif isinstance(data[field], Sensor):
                            raise ValidationError(
                                f"Please convert all flex-context prices to the unit of the {data[field]} sensor ({price_unit})."
                            )
                else:
                    field_name = price_field.data_key
                    raise ValidationError(
                        f"Prices must share the same monetary unit. '{field_name}' uses '{currency_unit}', but '{previous_field_name}' used '{shared_currency_unit}'.",
                        field_name=field_name,
                    )
        if shared_currency_unit is not None:
            data["shared_currency_unit"] = shared_currency_unit
        return data


class DBFlexContextSchema(FlexContextSchema):
    mapped_schema_keys = {
        field: FlexContextSchema().declared_fields[field].data_key
        for field in FlexContextSchema().declared_fields
    }

    @validates_schema
    def forbid_time_series_specs(self, data: dict, **kwargs):
        """Do not allow time series specs for the flex-context fields saved in the db."""

        # List of keys to check for time series specs
        keys_to_check = []
        # All the keys in this list are all fields of type VariableQuantity
        for field_var, field in self.declared_fields.items():
            if isinstance(field, VariableQuantityField):
                keys_to_check.append((field_var, field))

        # Check each key and raise a ValidationError if it's a list
        for field_var, field in keys_to_check:
            if field_var in data and isinstance(data[field_var], list):
                raise ValidationError(
                    "A time series specification (listing segments) is not supported when storing flex-context fields. Use a fixed quantity or a sensor reference instead.",
                    field_name=field.data_key,
                )

    @validates_schema
    def validate_fields_unit(self, data: dict, **kwargs):
        """Check that each field value has a valid unit."""

        self._validate_price_fields(data)
        self._validate_power_fields(data)
        self._validate_inflexible_device_sensors(data)

    def _validate_price_fields(self, data: dict):
        """Validate price fields."""
        energy_price_fields = [
            "consumption_price",
            "production_price",
        ]
        capacity_price_fields = [
            "ems_consumption_breach_price",
            "ems_production_breach_price",
            "ems_peak_consumption_price",
            "ems_peak_production_price",
        ]

        # Check that consumption and production prices are Sensors
        self._forbid_fixed_prices(data)

        for field in energy_price_fields:
            if field in data:
                self._validate_field(data, "energy price", field, is_energy_price_unit)
        for field in capacity_price_fields:
            if field in data:
                self._validate_field(
                    data, "capacity price", field, is_capacity_price_unit
                )

    def _validate_power_fields(self, data: dict):
        """Validate power fields."""
        power_fields = [
            "ems_power_capacity_in_mw",
            "ems_production_capacity_in_mw",
            "ems_consumption_capacity_in_mw",
            "ems_peak_consumption_in_mw",
            "ems_peak_production_in_mw",
        ]

        for field in power_fields:
            if field in data:
                self._validate_field(data, "power", field, is_power_unit)

    def _validate_field(self, data: dict, field_type: str, field: str, unit_validator):
        """Validate fields based on type and unit validator."""

        if isinstance(data[field], ur.Quantity):
            if not unit_validator(str(data[field].units)):
                raise ValidationError(
                    f"{field_type.capitalize()} field '{self.mapped_schema_keys[field]}' must have {p.a(field_type)} unit.",
                    field_name=self.mapped_schema_keys[field],
                )
        elif isinstance(data[field], Sensor):
            if not unit_validator(data[field].unit):
                raise ValidationError(
                    f"{field_type.capitalize()} field '{self.mapped_schema_keys[field]}' must have {p.a(field_type)} unit.",
                    field_name=self.mapped_schema_keys[field],
                )

    def _validate_inflexible_device_sensors(self, data: dict):
        """Validate inflexible device sensors."""
        if "inflexible_device_sensors" in data:
            for sensor in data["inflexible_device_sensors"]:
                if not is_power_unit(sensor.unit) and not is_energy_unit(sensor.unit):
                    raise ValidationError(
                        f"Inflexible device sensor '{sensor.id}' must have a power or energy unit.",
                        field_name="inflexible-device-sensors",
                    )

    def _forbid_fixed_prices(self, data: dict, **kwargs):
        """Do not allow fixed consumption price or fixed production price in the flex-context fields saved in the db.

        This is a temporary restriction as future iterations will allow fixed prices on these fields as well.
        """
        if "consumption_price" in data and isinstance(
            data["consumption_price"], ur.Quantity
        ):
            raise ValidationError(
                "Fixed prices are not currently supported for consumption-price in flex-context fields in the DB.",
                field_name="consumption-price",
            )

        if "production_price" in data and isinstance(
            data["production_price"], ur.Quantity
        ):
            raise ValidationError(
                "Fixed prices are not currently supported for production-price in flex-context fields in the DB.",
                field_name="production-price",
            )


def passthrough_deserializer():
    return lambda value, attr, data, **kwargs: value


class FlexContextTimeSeriesSchema(FlexContextSchema):
    """Schema for loading time series data for each VariableQuantityField in an already deserialized flex-context."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_time_series = True
        for field_var, field in self.declared_fields.items():
            if isinstance(field, VariableQuantityField) and field_var in (
                "consumption_breach_price",
                "production_breach_price",
                "soc_minima_breach_price",
                "soc_maxima_breach_price",
                "ems_consumption_breach_price",
                "ems_production_breach_price",
                "ems_peak_consumption_price",
                "ems_peak_production_price",
                "consumption_price",
                "production_price",
                "ems_power_capacity_in_mw",
                "ems_consumption_capacity_in_mw",
                "ems_production_capacity_in_mw",
                "ems_peak_consumption_in_mw",
                "ems_peak_production_in_mw",
            ):
                field.load_time_series = True
            # Compatibility with deprecated fields
            elif field_var in ("consumption_price_sensor", "production_price_sensor"):
                field.load_time_series = True
            else:
                # Skip deserialization
                field._deserialize = passthrough_deserializer()
            field.data_key = field_var
            setattr(self, field_var, field)


class MultiSensorFlexModelSchema(Schema):
    """

    This schema is agnostic to the underlying type of flex-model, which is governed by the chosen Scheduler instead.
    Therefore, the underlying type of flex-model is not deserialized.

    So:

        {
            "sensor": 1,
            "soc-at-start": "10 kWh"
        }

    becomes:

        {
            "sensor": <Sensor 1>,
            "sensor_flex_model": {
                "soc-at-start": "10 kWh"
            }
        }
    """

    sensor = SensorIdField(required=True)
    # it's up to the Scheduler to deserialize the underlying flex-model
    sensor_flex_model = fields.Dict(data_key="sensor-flex-model")

    @pre_load
    def unwrap_envelope(self, data, **kwargs):
        """Any field other than 'sensor' becomes part of the sensor's flex-model."""
        extra = {}
        rest = {}
        for k, v in data.items():
            if k not in self.fields:
                extra[k] = v
            else:
                rest[k] = v
        return {"sensor-flex-model": extra, **rest}

    @post_dump
    def wrap_with_envelope(self, data, **kwargs):
        """Any field in the 'sensor-flex-model' field becomes a main field."""
        sensor_flex_model = data.pop("sensor-flex-model", {})
        return dict(**data, **sensor_flex_model)


class AssetTriggerSchema(Schema):
    """
    {
        "start": "2025-01-21T15:00+01",
        "flex-model": [
            {
                "sensor": 1,
                "soc-at-start": "10 kWh"
            },
            {
                "sensor": 2,
                "soc-at-start": "20 kWh"
            },
        ]
    }
    """

    asset = GenericAssetIdField(data_key="id")
    start_of_schedule = AwareDateTimeField(
        data_key="start", format="iso", required=True
    )
    belief_time = AwareDateTimeField(format="iso", data_key="prior")
    duration = PlanningDurationField(load_default=PlanningDurationField.load_default)
    flex_model = fields.List(
        fields.Nested(MultiSensorFlexModelSchema()),
        data_key="flex-model",
    )
    flex_context = fields.Dict(required=False, data_key="flex-context")

    @validates_schema
    def check_flex_model_sensors(self, data, **kwargs):
        """Verify that the flex-model's sensors live under the asset for which a schedule is triggered."""
        asset = data["asset"]
        sensors = []
        for sensor_flex_model in data["flex_model"]:
            sensor = sensor_flex_model["sensor"]
            if sensor in sensors:
                raise FMValidationError(
                    f"Sensor {sensor_flex_model['sensor'].id} should not occur more than once in the flex-model"
                )
            if sensor.generic_asset not in [asset] + asset.offspring:
                raise FMValidationError(
                    f"Sensor {sensor_flex_model['sensor'].id} does not belong to asset {asset.id} (or to one of its offspring)"
                )
            sensors.append(sensor)
        return data
