from datetime import timedelta
from typing import List, Union

from flask_login import current_user
from isodate import datetime_isoformat, duration_isoformat
from marshmallow import fields, post_load, validates_schema, ValidationError
from marshmallow.validate import Equal, OneOf
from marshmallow_polyfield import PolyField
from timely_beliefs import BeliefsDataFrame
import pandas as pd

from flexmeasures.data import ma
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.api.common.schemas.sensors import SensorField
from flexmeasures.api.common.utils.api_utils import upsample_values
from flexmeasures.data.schemas.times import AwareDateTimeField, DurationField
from flexmeasures.data.services.time_series import simplify_index
from flexmeasures.utils.time_utils import server_now
from flexmeasures.utils.unit_utils import (
    convert_units,
    units_are_convertible,
)


class SingleValueField(fields.Float):
    """Field that both de-serializes and serializes a single value to a list of floats (length 1)."""

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

    Either will be de-serialized to [3.7].

    Note that serialization always results in a list of floats.
    This ensures that we are not requiring the same flexibility from users who are retrieving data.
    """
    if isinstance(values, list):
        return fields.List(fields.Float)
    else:
        return SingleValueField()


class SensorDataDescriptionSchema(ma.Schema):
    """
    Describing sensor data request (i.e. in a GET request).
    """

    type = fields.Str(required=True, validate=Equal("GetSensorDataRequest"))
    sensor = SensorField(required=True, entity_type="sensor", fm_scheme="fm1")
    start = AwareDateTimeField(required=True, format="iso")
    duration = DurationField(required=True)
    horizon = DurationField(required=False)
    prior = AwareDateTimeField(required=False, format="iso")
    unit = fields.Str(required=True)

    @validates_schema
    def check_user_rights_against_sensor(self, data, **kwargs):
        """If the user is a Prosumer and the sensor belongs to an asset
        over which the Prosumer has no ownership, raise a ValidationError.
        """
        # todo: implement check once sensors can belong to an asset
        #       https://github.com/FlexMeasures/flexmeasures/issues/155
        pass

    @validates_schema
    def check_schema_unit_against_sensor_unit(self, data, **kwargs):
        """Allows units compatible with that of the sensor.
        For example, a sensor with W units allows data to be posted with units:
        - W, kW, MW, etc. (i.e. units with different prefixes)
        - J/s, Nm/s, etc. (i.e. units that can be converted using some multiplier)
        - Wh, kWh, etc. (i.e. units that represent a stock delta, which knowing the duration can be converted to a flow)
        For compatible units, the SensorDataSchema converts values to the sensor's unit.
        """
        posted_unit = data["unit"]
        required_unit = data["sensor"].unit

        if posted_unit != required_unit and not units_are_convertible(
            posted_unit, required_unit
        ):
            raise ValidationError(
                f"Required unit for this sensor is {data['sensor'].unit}, got incompatible unit: {data['unit']}"
            )


class GetSensorDataSchema(SensorDataDescriptionSchema):

    @post_load
    def dump_bdf(self, sensor_data_description: dict, **kwargs) -> dict:
        sensor: Sensor = sensor_data_description["sensor"]
        start = sensor_data_description["start"]
        duration = sensor_data_description["duration"]
        end = sensor_data_description["start"] + duration
        unit = sensor_data_description["unit"]

        df = simplify_index(
            sensor.search_beliefs(
                event_starts_after=start,
                event_ends_before=end,
                horizons_at_least=sensor_data_description.get("horizon", None),
                beliefs_before=sensor_data_description.get("prior", None),
                one_deterministic_belief_per_event=True,
                as_json=False,
            )
        )

        # Convert to desired time range
        index = pd.date_range(
            start=start, end=end, freq=sensor.event_resolution, closed="left"
        )
        df = df.reindex(index)

        # Convert to desired unit
        values = convert_units(
            df["event_value"],
            from_unit=sensor.unit,
            to_unit=unit,
        )

        # Convert NaN to null
        values = values.where(pd.notnull(values), None)

        # Form the response
        response = dict(
            values=values.tolist(),
            start=datetime_isoformat(start),
            duration=duration_isoformat(duration),
            unit=unit,
        )

        return response


class PostSensorDataSchema(SensorDataDescriptionSchema):
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
    def post_load_sequence(self, data: dict, **kwargs) -> BeliefsDataFrame:
        """If needed, upsample and convert units, then deserialize to a BeliefsDataFrame."""
        data = self.possibly_upsample_values(data)
        data = self.possibly_convert_units(data)
        return self.load_bdf(data)

    @staticmethod
    def possibly_convert_units(data):
        """
        Convert values if needed, to fit the sensor's unit.
        Marshmallow runs this after validation.
        """
        data["values"] = convert_units(
            data["values"],
            from_unit=data["unit"],
            to_unit=data["sensor"].unit,
            event_resolution=data["sensor"].event_resolution,
        )
        return data

    @staticmethod
    def possibly_upsample_values(data):
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

    @staticmethod
    def load_bdf(sensor_data: dict) -> BeliefsDataFrame:
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

        # Work out what the recording time should be
        belief_timing = {}
        if "prior" in sensor_data:
            belief_timing["belief_time"] = sensor_data["prior"]
        elif "horizon" in sensor_data:
            belief_timing["belief_horizon"] = sensor_data["horizon"]
        else:
            belief_timing["belief_time"] = server_now()
        return BeliefsDataFrame(
            s,
            source=source,
            sensor=sensor_data["sensor"],
            **belief_timing,
        )
