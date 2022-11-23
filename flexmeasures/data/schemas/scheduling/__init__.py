from marshmallow import Schema, fields

from flexmeasures.data.schemas.sensors import SensorIdField


class FlexContextSchema(Schema):
    """
    This schema lists fields that can be used to describe sensors in the optimised portfolio
    """

    consumption_price_sensor = SensorIdField()
    production_price_sensor = SensorIdField()
    inflexible_device_sensors = fields.List(SensorIdField)
