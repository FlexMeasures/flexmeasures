from datetime import timedelta
from typing import List, Union

from flask_login import current_user
from marshmallow import fields, post_load, validates_schema, ValidationError
from marshmallow.validate import Equal, OneOf
from marshmallow_polyfield import PolyField
from timely_beliefs import BeliefsDataFrame
import pandas as pd

from flexmeasures.data import ma
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.api.common.schemas.sensors import SensorField
from flexmeasures.api.common.utils.api_utils import upsample_values
from flexmeasures.data.schemas.times import AwareDateTimeField, DurationField


class SingleValueField(fields.Float):
    """Field that both deserializes and serializes a single value to a list of floats (length 1)."""

    def _deserialize(self, value, attr, obj, **kwargs) -> List[float]:
        return [self._validated(value)]

    def _serialize(self, value, attr, data, **kwargs) -> List[float]:
        return [self._validated(value)]


def select_schema_to_ensure_list_of_floats(
    values: Union[List[float], float], _
) -> Union[fields.List, SingleValueField]:
    """Allows both a single float and a list of floats. Always returns a list of floats.

    Meant to improve user experience by not needing to make a list out of a single item, such that:

        {
            "values": [3.7]
        }

    can be written as:

        {
            "values": 3.7
        }

    Either will be deserialized to [3.7].

    Note that serialization always results in a list of floats.
    This ensures that we are not requiring the same flexibility from users who are retrieving data.
    """
    if isinstance(values, list):
        return fields.List(fields.Float)
    else:
        return SingleValueField()


class SensorDataDescriptionSchema(ma.Schema):
    """
    Describing sensor data (i.e. in a GET request).

    TODO: when we want to support other entity types with this
          schema (assets/weather/markets or actuators), we'll need some re-design.
    """

    type = fields.Str(required=True, validate=Equal("GetSensorDataRequest"))
    sensor = SensorField(required=True, entity_type="sensor", fm_scheme="fm1")
    start = AwareDateTimeField(required=True, format="iso")
    duration = DurationField(required=True)
    horizon = DurationField(
        required=False, missing=timedelta(hours=0), default=timedelta(hours=0)
    )
    unit = fields.Str(required=True)

    @validates_schema
    def check_user_rights_against_sensor(self, data, **kwargs):
        """If the user is a Prosumer and the sensor belongs to an asset
        over which the Prosumer has no ownership, raise a ValidationError.
        """
        # todo: implement check once sensors can belong to an asset
        #       https://github.com/SeitaBV/flexmeasures/issues/155
        pass

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
    values = PolyField(
        deserialization_schema_selector=select_schema_to_ensure_list_of_floats,
        serialization_schema_selector=select_schema_to_ensure_list_of_floats,
        many=False,
    )

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
            belief_horizon=sensor_data["horizon"],
        )
