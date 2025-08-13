from __future__ import annotations

from marshmallow import (
    Schema,
    fields,
    validate,
    validates_schema,
    ValidationError,
    pre_load,
    post_dump,
)

from flexmeasures import Sensor
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


class FlexContextSchema(Schema):
    """This schema defines fields that provide context to the portfolio to be optimized."""

    # Device commitments
    consumption_breach_price = VariableQuantityField(
        "/MW",
        data_key="consumption-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
    )
    production_breach_price = VariableQuantityField(
        "/MW",
        data_key="production-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
    )
    soc_minima_breach_price = VariableQuantityField(
        "/MWh",
        data_key="soc-minima-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
    )
    soc_maxima_breach_price = VariableQuantityField(
        "/MWh",
        data_key="soc-maxima-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
    )
    relax_constraints = fields.Bool(data_key="relax-constraints", load_default=False)
    # Dev fields
    relax_soc_constraints = fields.Bool(
        data_key="relax-soc-constraints", load_default=False
    )
    relax_capacity_constraints = fields.Bool(
        data_key="relax-capacity-constraints", load_default=False
    )
    relax_site_capacity_constraints = fields.Bool(
        data_key="relax-site-capacity-constraints", load_default=False
    )

    # Energy commitments
    ems_power_capacity_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-power-capacity",
        value_validator=validate.Range(min=0),
    )
    # todo: deprecated since flexmeasures==0.23
    consumption_price_sensor = SensorIdField(data_key="consumption-price-sensor")
    production_price_sensor = SensorIdField(data_key="production-price-sensor")
    consumption_price = VariableQuantityField(
        "/MWh",
        required=False,
        data_key="consumption-price",
        return_magnitude=False,
    )
    production_price = VariableQuantityField(
        "/MWh",
        required=False,
        data_key="production-price",
        return_magnitude=False,
    )

    # Capacity breach commitments
    ems_production_capacity_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-production-capacity",
        value_validator=validate.Range(min=0),
    )
    ems_consumption_capacity_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-consumption-capacity",
        value_validator=validate.Range(min=0),
    )
    ems_consumption_breach_price = VariableQuantityField(
        "/MW",
        data_key="site-consumption-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
    )
    ems_production_breach_price = VariableQuantityField(
        "/MW",
        data_key="site-production-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
    )

    # Peak consumption commitment
    ems_peak_consumption_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-peak-consumption",
        value_validator=validate.Range(min=0),
        load_default="0 kW",
    )
    ems_peak_consumption_price = VariableQuantityField(
        "/MW",
        data_key="site-peak-consumption-price",
        required=False,
        value_validator=validate.Range(min=0),
    )

    # Peak production commitment
    ems_peak_production_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-peak-production",
        value_validator=validate.Range(min=0),
        load_default="0 kW",
    )
    ems_peak_production_price = VariableQuantityField(
        "/MW",
        data_key="site-peak-production-price",
        required=False,
        value_validator=validate.Range(min=0),
    )
    # todo: group by month start (MS), something like a commitment resolution, or a list of datetimes representing splits of the commitments

    inflexible_device_sensors = fields.List(
        SensorIdField(), data_key="inflexible-device-sensors"
    )

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
            field_map[field] in data and data[field_map[field]]
            for field in (
                "soc-minima-breach-price",
                "soc-maxima-breach-price",
                "site-consumption-breach-price",
                "site-production-breach-price",
                "site-peak-consumption-price",
                "site-peak-production-price",
                "relax-constraints",
                "relax-soc-constraints",
                "relax-capacity-constraints",
                "relax-site-capacity-constraints",
                "consumption-breach-price",
                "production-breach-price",
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
        shared_currency = ur.Quantity(data["shared_currency_unit"])

        # Fill in default soc breach prices when asked to relax SoC constraints, unless already set explicitly.
        if (
            data["relax_soc_constraints"]
            or data["relax_constraints"]
            and not data.get("soc_minima_breach_price")
            and not data.get("soc_maxima_breach_price")
        ):
            self.set_default_breach_prices(
                data,
                fields=["soc_minima_breach_price", "soc_maxima_breach_price"],
                price=1000 * shared_currency / ur.Quantity("kWh"),
            )

        # Fill in default capacity breach prices when asked to relax capacity constraints, unless already set explicitly.
        if (
            data["relax_capacity_constraints"]
            or data["relax_constraints"]
            and not data.get("consumption_breach_price")
            and not data.get("production_breach_price")
        ):
            self.set_default_breach_prices(
                data,
                fields=["consumption_breach_price", "production_breach_price"],
                price=100 * shared_currency / ur.Quantity("kW"),
            )

        # Fill in default site capacity breach prices when asked to relax site capacity constraints, unless already set explicitly.
        if (
            data["relax_site_capacity_constraints"]
            or data["relax_constraints"]
            and not data.get("ems_consumption_breach_price")
            and not data.get("ems_production_breach_price")
        ):
            self.set_default_breach_prices(
                data,
                fields=["ems_consumption_breach_price", "ems_production_breach_price"],
                price=10000 * shared_currency / ur.Quantity("kW"),
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
                if not units_are_convertible(currency_unit, shared_currency_unit):
                    field_name = price_field.data_key
                    raise ValidationError(
                        f"Prices must share the same monetary unit. '{field_name}' uses '{currency_unit}', but '{previous_field_name}' used '{shared_currency_unit}'.",
                        field_name=field_name,
                    )
        if shared_currency_unit is not None:
            data["shared_currency_unit"] = shared_currency_unit
        elif sensor := data.get("consumption_price_sensor"):
            data["shared_currency_unit"] = self._to_currency_per_mwh(sensor.unit)
        elif sensor := data.get("production_price_sensor"):
            data["shared_currency_unit"] = self._to_currency_per_mwh(sensor.unit)
        else:
            data["shared_currency_unit"] = "dimensionless"
        return data

    @staticmethod
    def _to_currency_per_mwh(price_unit: str) -> str:
        """Convert a price unit to a base currency used to express that price per MWh.

        >>> FlexContextSchema()._to_currency_per_mwh("EUR/MWh")
        'EUR'
        >>> FlexContextSchema()._to_currency_per_mwh("EUR/kWh")
        'EUR'
        """
        currency = str(ur.Quantity(price_unit + " * MWh").to_base_units().units)
        return currency


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
    sequential = fields.Bool(load_default=False)

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
