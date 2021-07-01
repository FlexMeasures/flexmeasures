from datetime import timedelta

from marshmallow import fields, post_load, validates_schema, ValidationError

from flexmeasures.data import ma
from flexmeasures.api.common.schemas.sensors import SensorField
from flexmeasures.api.common.utils.api_utils import upsample_values
from flexmeasures.data.schemas.times import AwareDateTimeField, DurationField


class SensorDataDescriptionSchema(ma.Schema):
    """
    Describing sensor data (i.e. in a GET request).

    TODO: when we want to support other entity types with this
          schema (assets/weather/markets or actuators), we'll need some re-design.
    """

    type = fields.Str()  # type of request or response
    sensor = SensorField(entity_type="sensor", fm_scheme="fm1")
    start = AwareDateTimeField(format="iso")
    duration = DurationField()
    unit = fields.Str()


class SensorDataSchema(SensorDataDescriptionSchema):
    """
    This schema includes data, so it can be used for POST requests
    or GET responses.

    TODO: For the GET use case, look at api/common/validators.py::get_data_downsampling_allowed
          (sets a resolution parameter which we can pass to the data collection function).
    """

    @validates_schema
    def check_resolution_compatibility(self, data, **kwargs):
        inferred_resolution = data["duration"] / len(data["values"])
        required_resolution = data["sensor"].event_resolution
        # TODO: we don't yet have a good policy w.r.t. zero-resolution (direct measurement)
        if required_resolution == timedelta(hours=0):
            return
        if inferred_resolution % required_resolution != timedelta(hours=0):
            raise ValidationError(
                f"Resolution of {inferred_resolution} is incompatible with the sensor's required resolution of {required_resolution}."
            )

    @validates_schema
    def check_posted_unit_against_sensor_unit(self, data, **kwargs):
        if data["unit"] != data["sensor"].unit:
            raise ValidationError(
                f"Required unit for this sensor is {data['sensor'].unit}, got: {data['unit']}"
            )

    @post_load()
    def possibly_upsample_values(self, data, **kwargs):
        """
        Upsample the data if needed, to fit to the sensor's resolution.
        """
        inferred_resolution = data["duration"] / len(data["values"])
        required_resolution = data["sensor"].event_resolution

        # TODO: we don't yet have a good policy w.r.t. zero-resolution (direct measurement)
        if required_resolution == timedelta(hours=0):
            return data

        # we already know resolutions are compatible (see validation)
        if inferred_resolution != required_resolution:
            data["values"] = upsample_values(
                data["values"],
                from_resolution=inferred_resolution,
                to_resolution=required_resolution,
            )
        return data  # TODO: what should we return here?

    values = fields.List(fields.Float())
