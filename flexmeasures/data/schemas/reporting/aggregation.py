from marshmallow import fields, ValidationError, validates_schema, validate

from flexmeasures.data.schemas.reporting import (
    ReporterConfigSchema,
    ReporterParametersSchema,
)

from flexmeasures.data.schemas.io import Output


class AggregatorConfigSchema(ReporterConfigSchema):
    """Schema for the AggregatorReporter configuration

    Example:
    .. code-block:: json
        {
            "method" : "sum",
            "weights" : {
                "pv" : 1.0,
                "consumption" : -1.0
            }
        }
    """

    method = fields.Str(required=False, dump_default="sum", load_default="sum")
    weights = fields.Dict(fields.Str(), fields.Float(), required=False)


class AggregatorParametersSchema(ReporterParametersSchema):
    """Schema for the AggregatorReporter parameters

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

    # redefining output to restrict the output length to 1
    output = fields.List(
        fields.Nested(Output()), validate=validate.Length(min=1, max=1)
    )

    @validates_schema
    def validate_source(self, data, **kwargs):
        for input_description in data["input"]:
            if "source" not in input_description:
                raise ValidationError("`source` is a required field.")
