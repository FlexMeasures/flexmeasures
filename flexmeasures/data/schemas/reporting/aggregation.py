from marshmallow import fields, validate, validates_schema, ValidationError

from flexmeasures.data.schemas.reporting import (
    ReporterConfigSchema,
    ReporterParametersSchema,
)

from flexmeasures.data.schemas.io import Input, Output
from flexmeasures.data.schemas.scheduling.groups import GroupReferenceSchema


class MemberFilterSchema(ReporterConfigSchema):
    """Narrows a group down to some of its members.

    A group is a piece of shared equipment, so it holds everything behind that equipment.
    A filter picks a category out of it, such as every PV installation on a street.
    """

    asset_type = fields.Str(
        required=False,
        data_key="asset-type",
        metadata=dict(
            description="Keep only the members whose asset is of this type. The asset type says what a device is, which does not change when the way it is modelled changes.",
            examples=["solar", "battery"],
        ),
    )


class AggregatorConfigSchema(ReporterConfigSchema):
    """Schema for the AggregatorReporter configuration

    The sensors to aggregate come either from a device group of the flex-config, or from the `input` parameters.
    A group already says which devices sit behind one piece of equipment, which sensor records each of them,
    which sign means consumption or production, and where the group's aggregate belongs,
    so a report over a group needs no topology of its own.

    Example, aggregating the group on asset 2:
    .. code-block:: json
        {
            "group" : {"asset" : 2}
        }

    Example, aggregating only the PV installations of the group on asset 1:
    .. code-block:: json
        {
            "group" : {"asset" : 1},
            "members" : {"asset-type" : "solar"}
        }

    Example, aggregating sensors named in the parameters, which needs no group:
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

    group = fields.Nested(
        GroupReferenceSchema,
        required=False,
        metadata=dict(
            description="The device group to aggregate, as the flex-model's `group` field references it. The group's own entry says where its aggregate is recorded.",
        ),
    )
    members = fields.Nested(
        MemberFilterSchema,
        required=False,
        metadata=dict(
            description="Narrows the group down to some of its members. Only meaningful together with `group`.",
        ),
    )

    @validates_schema
    def check_members_needs_group(self, data: dict, **kwargs):
        if data.get("members") and not data.get("group"):
            raise ValidationError(
                "`members` filters the devices of a group, so it needs a `group` to filter.",
                field_name="members",
            )


class AggregatorParametersSchema(ReporterParametersSchema):
    """Schema for the AggregatorReporter parameters

    Both `input` and `output` are optional here, unlike in the base schema:
    a report over a device group takes its sensors, and the sensor it records on, from the flex-config.

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

    # redefining input, because the sensors to aggregate can also come from a device group
    input = fields.List(
        fields.Nested(Input()),
        required=False,
        load_default=list,
    )

    # redefining output, because the sensor to record on can also come from the group's own entry,
    # and because this reporter records on exactly one sensor
    output = fields.List(
        fields.Nested(Output()),
        required=False,
        load_default=list,
        validate=validate.Length(max=1),
    )
