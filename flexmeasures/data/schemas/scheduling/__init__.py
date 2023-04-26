from marshmallow import Schema, fields

from flexmeasures.data.schemas.sensors import SensorIdField


class FlexContextSchema(Schema):
    """
    This schema lists fields that can be used to describe sensors in the optimised portfolio
    """

    consumption_price_sensor = SensorIdField(data_key="consumption-price-sensor")
    production_price_sensor = SensorIdField(data_key="production-price-sensor")
    inflexible_device_sensors = fields.List(
        SensorIdField(), data_key="inflexible-device-sensors"
    )
    consumption_price_sensors_per_device = fields.Dict(
        SensorIdField(), SensorIdField(), data_key="consumption-price-sensors-per-device"
    )
    production_price_sensors_per_device = fields.Dict(
        SensorIdField(), SensorIdField(), data_key="production-price-sensors-per-device"
    )
