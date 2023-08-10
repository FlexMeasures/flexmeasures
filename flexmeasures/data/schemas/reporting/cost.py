from marshmallow import fields, ValidationError, validates_schema, validate, post_load

from flexmeasures.data.schemas.reporting import (
    ReporterConfigSchema,
    ReporterParametersSchema,
)

from flexmeasures.data.schemas.io import Input
from flexmeasures.data.schemas.sensors import SensorIdField


class CostReporterConfigSchema(ReporterConfigSchema):
    """Schema for the CostReporterReporter configuration

    Example:
    .. code-block:: json
        {
            "production-price-sensor" : 1,
            "consumption-price-sensor" : 2,
        }
    """

    consumption_price_sensor = SensorIdField(required=False)
    production_price_sensor = SensorIdField(required=False)

    @validates_schema
    def validate_price_sensors(self, data, **kwargs):
        """check that at least one of the price sensors is given"""
        if (
            "consumption_price_sensor" not in data
            and "production_price_sensor" not in data
        ):
            raise ValidationError(
                "At least one of the two price sensors, consumption or production, is required."
            )

    @post_load
    def complete_price_sensors(self, data, **kwargs):

        if "consumption_price_sensor" not in data:
            data["consumption_price_sensor"] = data["production_price_sensor"]
        if "production_price_sensor" not in data:
            data["production_price_sensor"] = data["consumption_price_sensor"]

        return data


class CostReporterParametersSchema(ReporterParametersSchema):
    """Schema for the CostReporterReporter parameters

    Example:
    .. code-block:: json
        {
            "input": [
                {
                    "sensor": 1,
                },
            ],
            "output": [
                {
                    "sensor": 2,
                }
            ],
            "start" : "2023-01-01T00:00:00+00:00",
            "end" : "2023-01-03T00:00:00+00:00",
        }
    """

    # redefining output to restrict the input length to 1
    input = fields.List(fields.Nested(Input()), validate=validate.Length(min=1, max=1))

    # # redefining output to restrict the output length to 1
    # output = fields.List(
    #     fields.Nested(Output()), validate=validate.Length(min=1, max=1)
    # )
