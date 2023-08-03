from marshmallow import fields, ValidationError, validates_schema, validate

from flexmeasures.data.schemas.reporting import (
    ReporterConfigSchema,
)

from flexmeasures.data.schemas.io import Input


class AggregatorConfigSchema(ReporterConfigSchema):
    """Schema for the reporter_config of the AggregatorReporter

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
            "method" : "sum",
            "weights" : {
                "pv" : 1.0,
                "consumption" : -1.0
            }
        }
    """

    method = fields.Str(required=False, dump_default="sum", load_default="sum")
    weights = fields.Dict(fields.Str(), fields.Float(), required=False)
    input = fields.List(
        fields.Nested(Input()),
        required=True,
        validator=validate.Length(min=1),
    )

    @validates_schema
    def validate_source(self, data, **kwargs):

        for input_description in data["input"]:
            if "source" not in input_description:
                raise ValidationError("`source` is a required field.")

    @validates_schema
    def validate_weights(self, data, **kwargs):
        if "weights" not in data:
            return

        # get names
        names = []
        for input_description in data["input"]:
            if "name" in input_description:
                names.append(input_description.get("name"))

        # check that the names in weights are defined in input
        for name in data.get("weights", {}).keys():
            if name not in names:
                raise ValidationError(
                    f"name `{name}` in `weights` is not defined in `input`"
                )
