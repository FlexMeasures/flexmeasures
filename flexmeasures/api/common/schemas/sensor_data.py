from datetime import timedelta

from flask_login import current_user
from marshmallow import fields, post_load, validates_schema, ValidationError
from marshmallow.validate import Equal, OneOf
from timely_beliefs import BeliefsDataFrame
import pandas as pd

from flexmeasures.data import ma
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.api.common.schemas.sensors import SensorField
from flexmeasures.api.common.utils.api_utils import upsample_values
from flexmeasures.data.schemas.times import AwareDateTimeField, DurationField


class SensorDataDescriptionSchema(ma.Schema):
    """
    Describing sensor data (i.e. in a GET request).

    TODO: Add an optional horizon field.
    TODO: when we want to support other entity types with this
          schema (assets/weather/markets or actuators), we'll need some re-design.
    """

    type = fields.Str(validate=Equal("GetSensorDataRequest"))
    sensor = SensorField(entity_type="sensor", fm_scheme="fm1")
    start = AwareDateTimeField(format="iso")
    duration = DurationField()
    unit = fields.Str()

    @validates_schema
    def check_schema_unit_against_sensor_unit(self, data, **kwargs):
        # TODO: technically, there are compatible units, like kWh and kW.
        #       They could be allowed here, and the SensorDataSchema could
        #       even convert values to the sensor's unit if possible.
        if data["unit"] != data["sensor"].unit:
            raise ValidationError(
                f"Required unit for this sensor is {data['sensor'].unit}, got: {data['unit']}"
            )


class SensorDataSchema(SensorDataDescriptionSchema):
    """
    This schema includes data, so it can be used for POST requests
    or GET responses.

    TODO: For the GET use case, look at api/common/validators.py::get_data_downsampling_allowed
          (sets a resolution parameter which we can pass to the data collection function).
    """

    type = fields.Str(
        validate=OneOf(["PostSensorDataRequest", "GetSensorDataResponse"])
    )
    values = fields.List(fields.Float())

    @validates_schema
    def check_resolution_compatibility_of_values(self, data, **kwargs):
        inferred_resolution = data["duration"] / len(data["values"])
        required_resolution = data["sensor"].event_resolution
        # TODO: we don't yet have a good policy w.r.t. zero-resolution (direct measurement)
        if required_resolution == timedelta(hours=0):
            return
        if inferred_resolution % required_resolution != timedelta(hours=0):
            raise ValidationError(
                f"Resolution of {inferred_resolution} is incompatible with the sensor's required resolution of {required_resolution}."
            )

    @post_load()
    def possibly_upsample_values(self, data, **kwargs):
        """
        Upsample the data if needed, to fit to the sensor's resolution.
        Marshmallow runs this after validation.
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
        return data

    def load_bdf(sensor_data) -> BeliefsDataFrame:
        """
        Turn the de-serialized and validated data into a BeliefsDataFrame.
        """
        source = DataSource.query.filter(
            DataSource.user_id == current_user.id
        ).one_or_none()
        if not source:
            raise ValidationError(
                f"User {current_user.id} is not an accepted data source."
            )

        num_values = len(sensor_data["values"])
        event_resolution = sensor_data["duration"] / num_values
        dt_index = pd.date_range(
            sensor_data["start"],
            periods=num_values,
            freq=event_resolution,
        )
        s = pd.Series(sensor_data["values"], index=dt_index)
        return BeliefsDataFrame(
            s,
            source=source,
            sensor=sensor_data["sensor"],
            belief_horizon=timedelta(hours=0),
        )
