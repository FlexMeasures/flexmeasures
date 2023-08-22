from marshmallow import (
    fields,
    ValidationError,
    validates_schema,
    validate,
    post_load,
    validates,
)

from flexmeasures.data.schemas.reporting import (
    ReporterConfigSchema,
    ReporterParametersSchema,
)

from flexmeasures.data.schemas.io import Input
from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.utils.unit_utils import is_currency_unit


class ProfitOrLossReporterConfigSchema(ReporterConfigSchema):
    """Schema for the ProfitOrLossReporter configuration

    Example:
    .. code-block:: json
        {
            "production-price-sensor" : 1,
            "consumption-price-sensor" : 2,
            "loss_is_positive" : True
        }
    """

    consumption_price_sensor = SensorIdField(required=False)
    production_price_sensor = SensorIdField(required=False)

    # set this to True to get the losses as positive values, otherwise, profit is positive.
    loss_is_positive = fields.Bool(
        load_default=False, dump_default=True, required=False
    )

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

    @validates("consumption_price_sensor")
    def validate_consumption_price_units(self, value):
        if not value.measures_energy_price:
            raise ValidationError(
                f"`consumption_price_sensor` has wrong units. Expected `Energy / Currency` but got `{value.unit}`"
            )

    @validates("production_price_sensor")
    def validate_production_price_units(self, value):
        if not value.measures_energy_price:
            raise ValidationError(
                f"`production_price_sensor` has wrong units. Expected `Energy / Currency` but got `{value.unit}`"
            )


class ProfitOrLossReporterParametersSchema(ReporterParametersSchema):
    """Schema for the ProfitOrLossReporter parameters

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

    @validates("input")
    def validate_input_measures_power_energy(self, value):
        if not (
            value[0]["sensor"].measures_power or value[0]["sensor"].measures_energy
        ):
            raise ValidationError(
                "Input sensor can only contain power or energy values."
            )

    @validates("output")
    def validate_output_unit_currency(self, value):
        for output_description in value:
            if not is_currency_unit(output_description["sensor"].unit):
                raise ValidationError(
                    "Output sensor unit can only be a currency, e.g. EUR."
                )
