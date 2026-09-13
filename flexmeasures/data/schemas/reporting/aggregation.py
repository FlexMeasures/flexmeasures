import re

from marshmallow import fields, validate, validates, ValidationError

from flexmeasures.data.schemas.reporting import (
    ReporterConfigSchema,
    ReporterParametersSchema,
)

from flexmeasures.data.schemas.generic_assets import GenericAssetIdField
from flexmeasures.data.schemas.io import Input, Output
from flexmeasures.data.schemas.sensors import SensorIdField


class AggregatorConfigSchema(ReporterConfigSchema):
    """Schema for the AggregatorReporter configuration

    Besides the aggregation method and the weights, this schema describes which sensors to aggregate.
    Sensors can be selected by asset, so that everything below a site asset is aggregated, and by an explicit list of sensor IDs.
    Both selections can be narrowed down by a regular expression on the sensor name, and by a list of units.

    Example:
    .. code-block:: json
        {
            "method" : "sum",
            "weights" : {
                "pv" : 1.0,
                "consumption" : -1.0
            }
        }

    Example, aggregating the power of every PV sensor below asset 3:
    .. code-block:: json
        {
            "method" : "sum",
            "asset" : 3,
            "sensor_name_pattern" : "(?i)pv",
            "sensor_units" : ["MW"]
        }
    """

    method = fields.Str(required=False, dump_default="sum", load_default="sum")
    weights = fields.Dict(fields.Str(), fields.Float(), required=False)

    asset = GenericAssetIdField(required=False)
    sensors = fields.List(SensorIdField(), required=False)
    sensor_name_pattern = fields.Str(required=False)
    sensor_units = fields.List(fields.Str(), required=False)

    convert_units = fields.Bool(required=False, dump_default=True, load_default=True)

    @validates("sensor_name_pattern")
    def validate_sensor_name_pattern(self, pattern: str, **kwargs):
        try:
            re.compile(pattern)
        except re.error as e:
            raise ValidationError(
                f"'{pattern}' is not a valid regular expression: {e}. Sensor names are matched with Python's `re` module."
            )


class AggregatorParametersSchema(ReporterParametersSchema):
    """Schema for the AggregatorReporter parameters

    The `input` field is optional here, unlike in the base schema, because the sensors to aggregate can also be selected in the reporter's configuration.

    Example:
    .. code-block:: json
        {
            "input": [
                {
                    "name" : "pv",
                    "sensor": 1,
                    "source" : 1,
                },
                {
                    "name" : "consumption",
                    "sensor": 1,
                    "source" : 2,
                }
            ],
            "output": [
                {
                    "sensor": 3,
                }
            ],
            "start" : "2023-01-01T00:00:00+00:00",
            "end" : "2023-01-03T00:00:00+00:00",
        }
    """

    # redefining input, because the sensors to aggregate can also come from the reporter's config
    input = fields.List(
        fields.Nested(Input()),
        required=False,
        load_default=list,
    )

    # redefining output to restrict the output length to 1
    output = fields.List(
        fields.Nested(Output()),
        required=True,
        validate=validate.Length(min=1, max=1),
    )
