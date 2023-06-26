from marshmallow import fields, ValidationError, validates_schema, validate

from flexmeasures.data.schemas.reporting import (
    ReporterConfigSchema,
    BeliefsSearchConfigSchema,
)


class AggregatorConfigSchema(ReporterConfigSchema):
    """Schema for the reporter_config of the AggregatorReporter

    Example:
    .. code-block:: json
        {
            "data": [
                {
                    "sensor": 1,
                    "source" : 1,
                    "alias" : "pv"
                },
                {
                    "sensor": 1,
                    "source" : 2,
                    "alias" : "consumption"
                }
            ],
            "method" : "sum",
            "weights" : {
                "pv" : 1.0,
                "consumption" : -1.0
            }
        }
    """

    method = fields.Str(required=False, dump_default="sum")
    weights = fields.Dict(fields.Str(), fields.Float(), required=False)
    data = fields.List(
        fields.Nested(BeliefsSearchConfigSchema()),
        required=True,
        validator=validate.Length(min=1),
    )

    @validates_schema
    def validate_source(self, data, **kwargs):

        for data in data["data"]:
            if "source" not in data:
                raise ValidationError("`source` is a required field.")

    @validates_schema
    def validate_weights(self, data, **kwargs):
        if "weights" not in data:
            return

        # get aliases
        aliases = []
        for data in data["data"]:
            if "alias" in data:
                aliases.append(data.get("alias"))

        # check that the aliases in weights are defined
        for alias in data.get("weights").keys():
            if alias not in aliases:
                raise ValidationError(
                    f"alias `{alias}` in `weights` is not defined in `data`"
                )
