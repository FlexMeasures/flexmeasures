from __future__ import annotations

import pint
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
from flexmeasures.utils.unit_utils import ur, units_are_convertible


class FlexContextSchema(Schema):
    """This schema defines fields that provide context to the portfolio to be optimized."""

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
        default=None,
    )
    ems_production_breach_price = VariableQuantityField(
        "/MW",
        data_key="site-production-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
        default=None,
    )

    # Peak consumption commitment
    ems_peak_consumption_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-peak-consumption",
        value_validator=validate.Range(min=0),
        default="0 kW",
    )
    ems_peak_consumption_price = VariableQuantityField(
        "/MW",
        data_key="site-peak-consumption-price",
        required=False,
        value_validator=validate.Range(min=0),
        default=None,
    )

    # Peak production commitment
    ems_peak_production_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-peak-production",
        value_validator=validate.Range(min=0),
        default="0 kW",
    )
    ems_peak_production_price = VariableQuantityField(
        "/MW",
        data_key="site-peak-production-price",
        required=False,
        value_validator=validate.Range(min=0),
        default=None,
    )
    # todo: group by month start (MS), something like a commitment resolution, or a list of datetimes representing splits of the commitments

    inflexible_device_sensors = fields.List(
        SensorIdField(), data_key="inflexible-device-sensors"
    )

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
            field_map[field] in data
            for field in (
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

        # All prices must share the same unit
        data = self._try_to_convert_price_units(data)

        return data

    def _try_to_convert_price_units(self, data):
        """Convert price units to the same unit and scale if they can (incl. same currency)."""

        previous_currency_unit = None
        previous_field_name = None
        for field in self.declared_fields:
            if field[-5:] == "price" and field in data:
                price_unit = self._get_variable_quantity_unit(field, data[field])
                price_field = self.declared_fields[field]
                currency_unit = price_unit.split("/")[0]

                if previous_currency_unit is None:
                    previous_currency_unit = currency_unit
                    previous_field_name = price_field.data_key
                elif units_are_convertible(currency_unit, previous_currency_unit):
                    # Make sure all compatible currency units are on the same scale (e.g. not kEUR mixed with EUR)
                    if currency_unit != previous_currency_unit:
                        denominator_unit = price_unit.split("/")[1]
                        if isinstance(data[field], ur.Quantity):
                            data[field] = data[field].to(
                                f"{previous_currency_unit}/{denominator_unit}"
                            )
                        elif isinstance(data[field], list):
                            for j in range(len(data[field])):
                                data[field][j]["value"] = data[field][j]["value"].to(
                                    f"{previous_currency_unit}/{denominator_unit}"
                                )
                        elif isinstance(data[field], Sensor):
                            raise ValidationError(
                                f"Please convert all flex-context prices to the unit of the {data[field]} sensor ({price_unit})."
                            )
                else:
                    field_name = price_field.data_key
                    raise ValidationError(
                        f"Prices must share the same monetary unit. '{field_name}' uses '{currency_unit}', but '{previous_field_name}' used '{previous_currency_unit}'.",
                        field_name=field_name,
                    )
        return data

    def _get_variable_quantity_unit(
        self, field: str, variable_quantity: ur.Quantity | list[dict | Sensor]
    ) -> str:
        """Gets the unit from the variable quantity."""
        if isinstance(variable_quantity, ur.Quantity):
            unit = str(variable_quantity.units)
        elif isinstance(variable_quantity, list):
            unit = str(variable_quantity[0]["value"].units)
            if not all(
                str(variable_quantity[j]["value"].units) == unit
                for j in range(len(variable_quantity))
            ):
                field_name = self.declared_fields[field].data_key
                raise ValidationError(
                    "Segments of a time series must share the same unit.",
                    field_name=field_name,
                )
        elif isinstance(variable_quantity, Sensor):
            unit = variable_quantity.unit
        else:
            raise NotImplementedError(
                f"Unexpected type '{type(variable_quantity)}' for '{field}': {variable_quantity}."
            )
        return unit


class DBFlexContextSchema(FlexContextSchema):

    @validates_schema
    def forbid_time_series_specs(self, data: dict, **kwargs):
        """Do not allow time series specs for the flex-context fields saved in the db."""

        keys_to_check = []
        # List of keys to check for time series specs
        # All the keys in this list are all fields of type VariableQuantity
        for field_var, field in self.declared_fields.items():
            if isinstance(field, VariableQuantityField):
                keys_to_check.append(field_var)

        # Check each key and raise a ValidationError if it's a list
        for key in keys_to_check:
            if key in data and isinstance(data[key], list):
                raise ValidationError(
                    f"Time series specs are not allowed in flex-context fields in the DB for '{key}'."
                )

    @validates_schema
    def forbid_fixed_prices(self, data: dict, **kwargs):
        """Do not allow fixed consumption price or fixed production price in the flex-context fields saved in the db."""
        if "consumption_price" in data and isinstance(
            data["consumption_price"], pint.Quantity
        ):
            raise ValidationError(
                "Fixed prices are not currently supported for consumption_price in flex-context fields in the DB."
            )

        if "production_price" in data and isinstance(
            data["production_price"], pint.Quantity
        ):
            raise ValidationError(
                "Fixed prices are not currently supported for production_price in flex-context fields in the DB."
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
