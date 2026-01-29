from __future__ import annotations
from typing import Any, Callable, Dict

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
from flexmeasures.data.schemas.scheduling import metadata
from flexmeasures.utils.doc_utils import rst_to_openapi
from flexmeasures.data.schemas.times import AwareDateTimeField, PlanningDurationField
from flexmeasures.data.schemas.utils import FMValidationError
from flexmeasures.utils.flexmeasures_inflection import p
from flexmeasures.utils.unit_utils import (
    ur,
    units_are_convertible,
    is_capacity_price_unit,
    is_energy_price_unit,
    is_power_unit,
    is_energy_unit,
)
from flexmeasures.utils.validation_utils import validate_variable_quantity


class NoTimeSeriesSpecs(Schema):

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


class CommitmentSchema(Schema):
    name = fields.Str(required=True, data_key="name")
    baseline = VariableQuantityField("MW", required=False, data_key="baseline")
    up_price = VariableQuantityField("/MW", required=False, data_key="up-price")
    down_price = VariableQuantityField(
        "/MW",
        required=False,
        data_key="down-price",
    )

    @validates_schema
    def check_units(self, commitment, **kwargs):
        baseline_field = self.declared_fields["baseline"]
        if "baseline" in commitment:
            baseline_unit = baseline_field._get_unit(commitment["baseline"])
        else:
            baseline_unit = "MW"
        if is_power_unit(baseline_unit):
            price_validators = [
                is_capacity_price_unit,
                is_energy_price_unit,
            ]  # one of these must pass
            allowed_price_units = ["power", "energy"]
        # todo: consider supporting more types of baselines here later
        # elif is_energy_unit(baseline_unit):
        #     baseline_validator = is_energy_unit
        #     price_validators = [is_energy_price_unit]
        #     unit_type = "energy"
        else:
            raise ValidationError(
                "Commitment baseline must have a power unit.",
                field_name="baseline",
            )

        def _ensure_variable_quantity_passes_one_validator(
            variable_quantity: ur.Quantity | Sensor | dict,
            validators: list[Callable],
            field_name: str,
            error_message: str,
        ):
            if not any(
                [
                    validate_variable_quantity(
                        variable_quantity=variable_quantity,
                        unit_validator=validator,
                        data_key=field_name,
                    )
                    for validator in validators
                ]
            ):
                raise ValidationError(
                    message=error_message,
                    field_name=field_name,
                )

        if "up_price" in commitment:
            _ensure_variable_quantity_passes_one_validator(
                variable_quantity=commitment["up_price"],
                validators=price_validators,
                field_name="up-price",
                error_message=f"Commitment up-price must have a {' or '.join(allowed_price_units)} unit in its denominator.",
            )
        if "down_price" in commitment:
            _ensure_variable_quantity_passes_one_validator(
                variable_quantity=commitment["down_price"],
                validators=price_validators,
                field_name="down-price",
                error_message=f"Commitment down-price must have a {' or '.join(allowed_price_units)} unit in its denominator.",
            )


class DBCommitmentSchema(CommitmentSchema, NoTimeSeriesSpecs):
    pass


class FlexContextSchema(Schema):
    """This schema defines fields that provide context to the portfolio to be optimized."""

    # Device commitments
    consumption_breach_price = VariableQuantityField(
        "/MW",
        data_key="consumption-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.CONSUMPTION_BREACH_PRICE.to_dict(),
    )
    production_breach_price = VariableQuantityField(
        "/MW",
        data_key="production-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.PRODUCTION_BREACH_PRICE.to_dict(),
    )
    soc_minima_breach_price = VariableQuantityField(
        "/MWh",
        data_key="soc-minima-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.SOC_MINIMA_BREACH_PRICE.to_dict(),
    )
    soc_maxima_breach_price = VariableQuantityField(
        "/MWh",
        data_key="soc-maxima-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.SOC_MAXIMA_BREACH_PRICE.to_dict(),
    )
    relax_constraints = fields.Bool(
        data_key="relax-constraints",
        load_default=False,
        metadata=metadata.RELAX_CONSTRAINTS.to_dict(),
    )
    # Dev fields
    relax_soc_constraints = fields.Bool(
        data_key="relax-soc-constraints",
        load_default=False,
        metadata=metadata.RELAX_SOC_CONSTRAINTS.to_dict(),
    )
    relax_capacity_constraints = fields.Bool(
        data_key="relax-capacity-constraints",
        load_default=False,
        metadata=metadata.RELAX_CAPACITY_CONSTRAINTS.to_dict(),
    )
    relax_site_capacity_constraints = fields.Bool(
        data_key="relax-site-capacity-constraints",
        load_default=False,
        metadata=metadata.RELAX_SITE_CAPACITY_CONSTRAINTS.to_dict(),
    )

    # Energy commitments
    ems_power_capacity_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-power-capacity",
        value_validator=validate.Range(min=0),
        metadata=metadata.SITE_POWER_CAPACITY.to_dict(),
    )
    # todo: deprecated since flexmeasures==0.23
    consumption_price_sensor = SensorIdField(data_key="consumption-price-sensor")
    production_price_sensor = SensorIdField(data_key="production-price-sensor")
    consumption_price = VariableQuantityField(
        "/MWh",
        required=False,
        data_key="consumption-price",
        return_magnitude=False,
        metadata=metadata.CONSUMPTION_PRICE.to_dict(),
    )
    production_price = VariableQuantityField(
        "/MWh",
        required=False,
        data_key="production-price",
        return_magnitude=False,
        metadata=metadata.PRODUCTION_PRICE.to_dict(),
    )

    # Capacity breach commitments
    ems_production_capacity_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-production-capacity",
        value_validator=validate.Range(min=0),
        metadata=metadata.SITE_PRODUCTION_CAPACITY.to_dict(),
    )
    ems_consumption_capacity_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-consumption-capacity",
        value_validator=validate.Range(min=0),
        metadata=metadata.SITE_CONSUMPTION_CAPACITY.to_dict(),
    )
    ems_consumption_breach_price = VariableQuantityField(
        "/MW",
        data_key="site-consumption-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.SITE_CONSUMPTION_BREACH_PRICE.to_dict(),
    )
    ems_production_breach_price = VariableQuantityField(
        "/MW",
        data_key="site-production-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.SITE_PRODUCTION_BREACH_PRICE.to_dict(),
    )

    # Peak consumption commitment
    ems_peak_consumption_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-peak-consumption",
        value_validator=validate.Range(min=0),
        load_default=ur.Quantity("0 kW"),
        metadata=metadata.SITE_PEAK_CONSUMPTION.to_dict(),
    )
    ems_peak_consumption_price = VariableQuantityField(
        "/MW",
        data_key="site-peak-consumption-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.SITE_PEAK_CONSUMPTION_PRICE.to_dict(),
    )

    # Peak production commitment
    ems_peak_production_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-peak-production",
        value_validator=validate.Range(min=0),
        load_default=ur.Quantity("0 kW"),
        metadata=metadata.SITE_PEAK_PRODUCTION.to_dict(),
    )
    ems_peak_production_price = VariableQuantityField(
        "/MW",
        data_key="site-peak-production-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.SITE_PEAK_PRODUCTION_PRICE.to_dict(),
    )
    # todo: group by month start (MS), something like a commitment resolution, or a list of datetimes representing splits of the commitments

    commitments = fields.Nested(
        CommitmentSchema,
        data_key="commitments",
        required=False,
        many=True,
        metadata=metadata.COMMITMENTS.to_dict(),
    )

    inflexible_device_sensors = fields.List(
        SensorIdField(),
        data_key="inflexible-device-sensors",
        metadata=metadata.INFLEXIBLE_DEVICE_SENSORS.to_dict(),
    )

    curtailable_device_sensors = fields.List(
        SensorIdField(),
        data_key="curtailable-device-sensors",
        metadata=metadata.CURTAILABLE_DEVICE_SENSORS.to_dict(),
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

    @validates_schema(pass_original=True)
    def check_prices(self, data: dict, original_data: dict, **kwargs):
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
        data = self._try_to_convert_price_units(data, original_data)
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

    def _try_to_convert_price_units(self, data: dict, original_data: dict):
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
                    original_price_unit = price_field._get_original_unit(
                        original_data[field_name], data[field]
                    )
                    error_message = f"Invalid unit. A valid unit would be, for example, '{shared_currency_unit + price_field.to_unit}' (this example uses '{shared_currency_unit}', because '{previous_field_name}' used that currency). However, you passed an incompatible price ('{original_price_unit}') for the '{field_name}' field."
                    if shared_currency_unit not in price_unit:
                        error_message += f" Also note that all prices in the flex-context must share the same currency unit (in this case: '{shared_currency_unit}')."
                    raise ValidationError(error_message, field_name=field_name)
        if shared_currency_unit is not None:
            data["shared_currency_unit"] = shared_currency_unit
        elif sensor := data.get("consumption_price_sensor"):
            data["shared_currency_unit"] = self._to_currency_per_mwh(sensor.unit)
        elif sensor := data.get("production_price_sensor"):
            data["shared_currency_unit"] = self._to_currency_per_mwh(sensor.unit)
        else:
            data["shared_currency_unit"] = "EUR"
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


EXAMPLE_UNIT_TYPES: Dict[str, list[str]] = {
    "energy-price": ["EUR/MWh", "JPY/kWh", "USD/MWh", "and other currencies."],
    "power-price": ["EUR/kW", "JPY/kW", "USD/kW", "and other currencies."],
    "power": ["MW", "kW"],
    "energy": ["MWh", "kWh"],
    "boolean": ["Boolean"],
    "efficiency": ["%"],
}

UI_FLEX_CONTEXT_SCHEMA: Dict[str, Dict[str, Any]] = {
    "consumption-price": {
        "default": None,  # Refers to default value of the field
        "description": rst_to_openapi(metadata.CONSUMPTION_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["energy-price"],
    },
    "production-price": {
        "default": None,
        "description": rst_to_openapi(metadata.PRODUCTION_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["energy-price"],
    },
    "site-power-capacity": {
        "default": None,
        "description": rst_to_openapi(metadata.SITE_POWER_CAPACITY.description),
        "example-units": ["kVA", "MVA"] + EXAMPLE_UNIT_TYPES["power"],
    },
    "site-production-capacity": {
        "default": None,
        "description": rst_to_openapi(metadata.SITE_PRODUCTION_CAPACITY.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "site-consumption-capacity": {
        "default": None,
        "description": rst_to_openapi(metadata.SITE_CONSUMPTION_CAPACITY.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "soc-minima-breach-price": {
        "default": None,
        "description": rst_to_openapi(metadata.SOC_MINIMA_BREACH_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["energy-price"],
    },
    "soc-maxima-breach-price": {
        "default": None,
        "description": rst_to_openapi(metadata.SOC_MAXIMA_BREACH_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["energy-price"],
    },
    "consumption-breach-price": {
        "default": None,
        "description": rst_to_openapi(metadata.CONSUMPTION_BREACH_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["power-price"],
    },
    "production-breach-price": {
        "default": None,
        "description": rst_to_openapi(metadata.PRODUCTION_BREACH_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["power-price"],
    },
    "site-consumption-breach-price": {
        "default": None,
        "description": rst_to_openapi(
            metadata.SITE_CONSUMPTION_BREACH_PRICE.description
        ),
        "example-units": EXAMPLE_UNIT_TYPES["power-price"],
    },
    "site-production-breach-price": {
        "default": None,
        "description": rst_to_openapi(
            metadata.SITE_PRODUCTION_BREACH_PRICE.description
        ),
        "example-units": EXAMPLE_UNIT_TYPES["power-price"],
    },
    "site-peak-consumption": {
        "default": None,
        "description": rst_to_openapi(metadata.SITE_PEAK_CONSUMPTION.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "site-peak-production": {
        "default": None,
        "description": rst_to_openapi(metadata.SITE_PEAK_PRODUCTION.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "site-peak-consumption-price": {
        "default": None,
        "description": rst_to_openapi(metadata.SITE_PEAK_CONSUMPTION_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["power-price"],
    },
    "site-peak-production-price": {
        "default": None,
        "description": rst_to_openapi(metadata.SITE_PEAK_PRODUCTION_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["power-price"],
    },
    "inflexible-device-sensors": {
        "default": [],
        "description": rst_to_openapi(metadata.INFLEXIBLE_DEVICE_SENSORS.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "commitments": {
        "default": None,
        "description": rst_to_openapi(metadata.COMMITMENTS.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
}

UI_FLEX_MODEL_SCHEMA: Dict[str, Dict[str, Any]] = {
    "soc-min": {
        "default": None,
        "description": rst_to_openapi(metadata.SOC_MIN.description),
        "types": {
            "backend": "typeThree",
            "ui": "One fixed value or a dynamic signal (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["energy"],
    },
    "soc-max": {
        "default": None,
        "description": rst_to_openapi(metadata.SOC_MAX.description),
        "types": {
            "backend": "typeThree",
            "ui": "One fixed value or a dynamic signal (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["energy"],
    },
    "soc-minima": {
        "default": None,
        "description": rst_to_openapi(metadata.SOC_MINIMA.description),
        "types": {
            "backend": "typeTwo",
            "ui": "A sensor which records the state of charge.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["energy"],
    },
    "soc-maxima": {
        "default": None,
        "description": rst_to_openapi(metadata.SOC_MAXIMA.description),
        "types": {
            "backend": "typeTwo",
            "ui": "A sensor which records the state of charge.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["energy"],
    },
    "soc-targets": {
        "default": None,
        "description": rst_to_openapi(metadata.SOC_TARGETS.description),
        "types": {
            "backend": "typeTwo",
            "ui": "A sensor which records the state of charge.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["energy"],
    },
    "state-of-charge": {
        "default": None,
        "description": rst_to_openapi(metadata.STATE_OF_CHARGE.description),
        "types": {
            "backend": "typeTwo",
            "ui": "A sensor which records the state of charge.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["energy"],
    },
    "soc-gain": {
        "default": [],
        "description": rst_to_openapi(metadata.SOC_GAIN.description),
        "types": {
            "backend": "typeFour",
            "ui": "Multiple settings possible - either fixed values or dynamic signals (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "soc-usage": {
        "default": [],
        "description": rst_to_openapi(metadata.SOC_USAGE.description),
        "types": {
            "backend": "typeFour",
            "ui": "Multiple settings possible - either fixed values or dynamic signals (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "roundtrip-efficiency": {
        "default": None,
        "description": rst_to_openapi(metadata.ROUNDTRIP_EFFICIENCY.description),
        "types": {
            "backend": "typeFive",
            "ui": "Fixed value only.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["efficiency"],
    },
    "charging-efficiency": {
        "default": None,
        "description": rst_to_openapi(metadata.CHARGING_EFFICIENCY.description),
        "types": {
            "backend": "typeFive",
            "ui": "Fixed value only.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["efficiency"],
    },
    "discharging-efficiency": {
        "default": None,
        "description": rst_to_openapi(metadata.DISCHARGING_EFFICIENCY.description),
        "types": {
            "backend": "typeFive",
            "ui": "Fixed value only.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["efficiency"],
    },
    "storage-efficiency": {
        "default": None,
        "description": rst_to_openapi(metadata.STORAGE_EFFICIENCY.description),
        "types": {
            "backend": "typeFive",
            "ui": "Fixed value only.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["efficiency"],
    },
    "prefer-charging-sooner": {
        "default": None,
        "description": rst_to_openapi(metadata.PREFER_CHARGING_SOONER.description),
        "types": {
            "backend": "typeOne",
            "ui": "Boolean option only.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["boolean"],
    },
    "prefer-curtailing-later": {
        "default": None,
        "description": rst_to_openapi(metadata.PREFER_CURTAILING_LATER.description),
        "types": {
            "backend": "typeOne",
            "ui": "Boolean option only.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["boolean"],
    },
    "power-capacity": {
        "default": None,
        "description": rst_to_openapi(metadata.POWER_CAPACITY.description),
        "types": {
            "backend": "typeThree",
            "ui": "One fixed value or a dynamic signal (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "consumption-capacity": {
        "default": None,
        "description": rst_to_openapi(metadata.CONSUMPTION_CAPACITY.description),
        "types": {
            "backend": "typeThree",
            "ui": "One fixed value or a dynamic signal (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "production-capacity": {
        "default": None,
        "description": rst_to_openapi(metadata.PRODUCTION_CAPACITY.description),
        "types": {
            "backend": "typeThree",
            "ui": "One fixed value or a dynamic signal (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
}


class DBFlexContextSchema(FlexContextSchema, NoTimeSeriesSpecs):

    commitments = fields.Nested(
        DBCommitmentSchema, data_key="commitments", required=False, many=True
    )
    mapped_schema_keys = {
        field: FlexContextSchema().declared_fields[field].data_key
        for field in FlexContextSchema().declared_fields
    }

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
            "soc_minima_breach_price",
            "soc_maxima_breach_price",
        ]
        capacity_price_fields = [
            "consumption_breach_price",
            "production_breach_price",
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

    sensor = SensorIdField(required=False)
    asset = GenericAssetIdField(required=False)
    # it's up to the Scheduler to deserialize the underlying flex-model
    sensor_flex_model = fields.Dict(data_key="sensor-flex-model")

    @validates_schema
    def ensure_sensor_or_asset(self, data, **kwargs):
        if (
            "sensor" in data
            and "asset" in data
            and data["sensor"].asset != data["asset"]
        ):
            raise ValidationError("Sensor does not belong to asset.")
        if "sensor" not in data and "asset" not in data:
            raise ValidationError("Specify either a sensor or an asset.")

    @pre_load
    def unwrap_envelope(self, data, **kwargs):
        """Any field other than 'sensor' and 'asset' becomes part of the sensor's flex-model."""
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

    asset = GenericAssetIdField(
        data_key="id",
        metadata=dict(
            description="ID of the asset that is requested to be scheduled. Together with its children and their further offspring, the asset may represent a tree of assets, in which case the whole asset tree will be taken into account.",
        ),
    )
    start_of_schedule = AwareDateTimeField(
        data_key="start",
        format="iso",
        required=True,
        metadata=dict(
            description="Start time of the schedule, in ISO 8601 datetime format.",
            example="2026-01-15T10:00+01:00",
        ),
    )
    belief_time = AwareDateTimeField(
        format="iso",
        data_key="prior",
        description="The scheduler is only allowed to take into account sensor data that has been recorded prior to this [belief time](https://flexmeasures.readthedocs.io/latest/api/notation.html#tracking-the-recording-time-of-beliefs). "
        "By default, the most recent sensor data is used. This field is especially useful for running simulations.",
        example="2026-01-15T10:00+01:00",
    )
    duration = PlanningDurationField(
        load_default=PlanningDurationField.load_default,
        metadata=dict(
            description="The duration for which to create the schedule, also known as the planning horizon, in ISO 8601 duration format.",
            example="PT24H",
        ),
    )
    flex_model = fields.List(
        fields.Nested(MultiSensorFlexModelSchema()),
        data_key="flex-model",
    )
    flex_context = fields.Dict(
        required=False,
        data_key="flex-context",
    )
    sequential = fields.Bool(
        load_default=False,
        metadata=dict(
            description="If true, each asset within the asset tree is scheduled one after the other, where the next schedule takes into account the previously scheduled assets as inflexible device.",
        ),
    )

    @validates_schema
    def check_flex_model_sensors(self, data, **kwargs):
        """Verify that the flex-model's sensors live under the asset for which a schedule is triggered."""
        asset = data["asset"]
        sensors = []
        for sensor_flex_model in data.get("flex_model", []):
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
