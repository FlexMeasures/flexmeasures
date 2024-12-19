from __future__ import annotations

from marshmallow import Schema, fields, validate, validates_schema, ValidationError

from flexmeasures import Sensor
from flexmeasures.data.schemas.sensors import (
    VariableQuantityField,
    SensorIdField,
)
from flexmeasures.utils.unit_utils import ur, units_are_convertible


class FlexContextSchema(Schema):
    """
    This schema lists fields that can be used to describe sensors in the optimised portfolio
    """

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
