from marshmallow import fields

from flexmeasures.data import ma
from flexmeasures.api.common.schemas.sensors import SensorField
from flexmeasures.data.schemas.times import AwareDateTimeField, DurationField


class SensorDataDescriptionSchema(ma.Schema):
    """
    Describing sensor data (i.e. in a GET request).

    TODO: when we want to support other entity types with this
          schema (assets/weather/markets or sensors/actuators), we'll need some re-design.
    """

    type = fields.Str()  # type of request or response
    connection = SensorField(entity_type="sensor", fm_scheme="fm1")
    start = AwareDateTimeField(format="iso")
    duration = DurationField()
    unit = fields.Str()


class SensorDataSchema(SensorDataDescriptionSchema):
    """
    This schema includes data, so it can be used for POST requests
    or GET responses.
    """

    values = fields.List(fields.Float())
