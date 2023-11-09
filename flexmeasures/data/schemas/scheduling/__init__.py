from marshmallow import Schema, fields, validate

from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.schemas.units import QuantityField


class FlexContextSchema(Schema):
    """
    This schema lists fields that can be used to describe sensors in the optimised portfolio
    """

    ems_power_capacity_in_mw = QuantityField(
        "MW",
        required=False,
        data_key="site-power-capacity",
        validate=validate.Range(min=0),
    )
    ems_production_capacity_in_mw = QuantityField(
        "MW",
        required=False,
        data_key="site-production-capacity",
        validate=validate.Range(min=0),
    )
    ems_consumption_capacity_in_mw = QuantityField(
        "MW",
        required=False,
        data_key="site-consumption-capacity",
        validate=validate.Range(min=0),
    )
    consumption_price_sensor = SensorIdField(data_key="consumption-price-sensor")
    production_price_sensor = SensorIdField(data_key="production-price-sensor")
    inflexible_device_sensors = fields.List(
        SensorIdField(), data_key="inflexible-device-sensors"
    )
