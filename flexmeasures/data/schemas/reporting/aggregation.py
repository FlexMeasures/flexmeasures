from marshmallow import fields, ValidationError, validates_schema

from flexmeasures.data.schemas.reporting import ReporterConfigSchema

from enum import Enum


class AggregationMethod(Enum):
    SUM = "SUM"
    MEAN = "MEAN"


class AggregatorSchema(ReporterConfigSchema):
    """Schema for the reporter_config of the AggregatorReporter

    Example:
    .. code-block:: json
        {
            "beliefs_search_configs": [
                {
                    "sensor": 1,
                    "source" : 1,
                    "alias" : "PV"
                },
                {
                    "sensor": 1,
                    "source" : 2,
                    "alias" : "CONSUMPTION"
                }
            ],
            "method" : "SUM",
            "weights" : {
                "PV" : 1.0,
                "CONSUMPTION" : -1.0
            }
        }
    """

    method = fields.Enum(AggregationMethod, required=True)
    weights = fields.Dict(fields.Str(), fields.Float())

    @validates_schema
    def validate_source(self, data, **kwargs):

        for beliefs_search_config in data["beliefs_search_configs"]:
            if "source" not in beliefs_search_config:
                raise ValidationError("`source` is a required field.")

    @validates_schema
    def validate_weights(self, data, **kwargs):
        if "weights" not in data:
            return

        # get aliases
        aliases = []
        for beliefs_search_config in data["beliefs_search_configs"]:
            if "alias" in beliefs_search_config:
                aliases.append(beliefs_search_config.get("alias"))

        # check the the aliases in weights are defined
        for alias in data.get("weights").keys():
            if alias not in aliases:
                raise ValidationError(
                    f"alias `{alias}` not defined in `beliefs_search_config`"
                )
