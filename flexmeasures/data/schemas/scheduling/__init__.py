from marshmallow import Schema, fields, validate, validates_schema, ValidationError
from werkzeug.exceptions import Forbidden

from flexmeasures.auth.policy import check_access
from flexmeasures.data.schemas.scheduling.utils import find_sensors
from flexmeasures.data.schemas.sensors import QuantityOrSensor, SensorIdField


class FlexContextSchema(Schema):
    """This schema defines fields that provide context to the portfolio to be optimized."""

    ems_power_capacity_in_mw = QuantityOrSensor(
        "MW",
        required=False,
        data_key="site-power-capacity",
        validate=validate.Range(min=0),
    )
    ems_production_capacity_in_mw = QuantityOrSensor(
        "MW",
        required=False,
        data_key="site-production-capacity",
        validate=validate.Range(min=0),
    )
    ems_consumption_capacity_in_mw = QuantityOrSensor(
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

    @validates_schema
    def check_read_access_on_sensors(self, data: dict, **kwargs):
        sensors = find_sensors(data)
        for sensor, field_name in sensors:
            try:
                check_access(context=sensor, permission="read")
            except Forbidden:
                raise ValidationError(
                    message=f"User has no read access to sensor {sensor.id}.",
                    field_name=self.fields[field_name].data_key,
                )
