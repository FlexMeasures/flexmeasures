from __future__ import annotations

from datetime import timedelta

from flask_login import current_user
from isodate import datetime_isoformat
from marshmallow import fields, post_load, validates_schema, ValidationError
from marshmallow.validate import OneOf, Length
from marshmallow_polyfield import PolyField
from timely_beliefs import BeliefsDataFrame
import pandas as pd

from flexmeasures.data import ma
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.api.common.schemas.sensors import SensorField
from flexmeasures.api.common.utils.api_utils import upsample_values
from flexmeasures.data.models.planning.utils import initialize_index
from flexmeasures.data.schemas import AwareDateTimeField, DurationField, SourceIdField
from flexmeasures.data.services.data_sources import get_or_create_source
from flexmeasures.data.services.time_series import simplify_index
from flexmeasures.utils.time_utils import (
    decide_resolution,
    duration_isoformat,
    server_now,
)
from flexmeasures.utils.unit_utils import (
    convert_units,
    units_are_convertible,
    is_energy_price_unit,
)


class SingleValueField(fields.Float):
    """Field that both de-serializes and serializes a single value to a list of floats (length 1)."""

    def _deserialize(self, value, attr, obj, **kwargs) -> list[float]:
        return [self._validated(value)]

    def _serialize(self, value, attr, data, **kwargs) -> list[float]:
        return [self._validated(value)]


def select_schema_to_ensure_list_of_floats(
    values: list[float] | float, _
) -> fields.List | SingleValueField:
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
        return fields.List(fields.Float(allow_none=True), validate=Length(min=1))
    else:
        return SingleValueField()


class SensorDataDescriptionSchema(ma.Schema):
    """
    Schema describing sensor data (specifically, the sensor and the timing of the data).
    """

    sensor = SensorField(required=True, entity_type="sensor", fm_scheme="fm1")
    start = AwareDateTimeField(required=True, format="iso")
    duration = DurationField(required=True)
    horizon = DurationField(required=False)
    prior = AwareDateTimeField(required=False, format="iso")
    unit = fields.Str(required=True)

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
    resolution = DurationField(required=False)
    source = SourceIdField(required=False)

    # Optional field that can be used for extra validation
    type = fields.Str(
        required=False,
        validate=OneOf(
            [
                "GetSensorDataRequest",
                "GetMeterDataRequest",
                "GetPrognosisRequest",
                "GetPriceDataRequest",
            ]
        ),
    )

    @validates_schema
    def check_schema_unit_against_type(self, data, **kwargs):
        requested_unit = data["unit"]
        _type = data.get("type", None)
        if _type in (
            "GetMeterDataRequest",
            "GetPrognosisRequest",
        ) and not units_are_convertible(requested_unit, "MW"):
            raise ValidationError(
                f"The unit requested for this message type should be convertible from MW, got incompatible unit: {requested_unit}"
            )
        elif _type == "GetPriceDataRequest" and not is_energy_price_unit(
            requested_unit
        ):
            raise ValidationError(
                f"The unit requested for this message type should be convertible from an energy price unit, got incompatible unit: {requested_unit}"
            )

    @staticmethod
    def load_data_and_make_response(sensor_data_description: dict) -> dict:
        """Turn the de-serialized and validated data description into a response.

        Specifically, this function:
        - queries data according to the given description
        - converts to a single deterministic belief per event
        - ensures the response respects the requested time frame
        - converts values to the requested unit
        - converts values to the requested resolution
        """
        sensor: Sensor = sensor_data_description["sensor"]
        start = sensor_data_description["start"]
        duration = sensor_data_description["duration"]
        end = sensor_data_description["start"] + duration
        unit = sensor_data_description["unit"]
        resolution = sensor_data_description.get("resolution")
        source = sensor_data_description.get("source")

        # Post-load configuration of event frequency
        if resolution is None:
            if sensor.event_resolution != timedelta(hours=0):
                resolution = sensor.event_resolution
            else:
                # For instantaneous sensors, choose a default resolution given the requested time window
                resolution = decide_resolution(start, end)

        # Post-load configuration of belief timing against message type
        horizons_at_least = sensor_data_description.get("horizon", None)
        horizons_at_most = None
        _type = sensor_data_description.get("type", None)
        if _type == "GetMeterDataRequest":
            horizons_at_most = timedelta(0)
        elif _type == "GetPrognosisRequest":
            if horizons_at_least is None:
                horizons_at_least = timedelta(0)
            else:
                # If the horizon field is used, ensure we still respect the minimum horizon for prognoses
                horizons_at_least = max(horizons_at_least, timedelta(0))

        df = simplify_index(
            sensor.search_beliefs(
                event_starts_after=start,
                event_ends_before=end,
                horizons_at_least=horizons_at_least,
                horizons_at_most=horizons_at_most,
                source=source,
                beliefs_before=sensor_data_description.get("prior", None),
                one_deterministic_belief_per_event=True,
                resolution=resolution,
                as_json=False,
            )
        )

        # Convert to desired time range
        index = initialize_index(start=start, end=end, resolution=resolution)
        df = df.reindex(index)

        # Convert to desired unit
        values: pd.Series = convert_units(  # type: ignore
            df["event_value"],
            from_unit=sensor.unit,
            to_unit=unit,
        )

        # Convert NaN to None, which JSON dumps as null values
        values = values.astype(object).where(pd.notnull(values), None)

        # Form the response
        response = dict(
            values=values.tolist(),
            start=datetime_isoformat(start),
            duration=duration_isoformat(duration),
            unit=unit,
            resolution=duration_isoformat(df.event_resolution),
        )

        return response


class PostSensorDataSchema(SensorDataDescriptionSchema):
    """
    This schema includes data, so it can be used for POST requests
    or GET responses.

    TODO: For the GET use case, look at api/common/validators.py::get_data_downsampling_allowed
          (sets a resolution parameter which we can pass to the data collection function).
    """

    # Optional field that can be used for extra validation
    type = fields.Str(
        required=False,
        validate=OneOf(
            [
                "PostSensorDataRequest",
                "PostMeterDataRequest",
                "PostPrognosisRequest",
                "PostPriceDataRequest",
                "PostWeatherDataRequest",
            ]
        ),
    )
    values = PolyField(
        deserialization_schema_selector=select_schema_to_ensure_list_of_floats,
        serialization_schema_selector=select_schema_to_ensure_list_of_floats,
        many=False,
    )

    @validates_schema
    def check_schema_unit_against_type(self, data, **kwargs):
        posted_unit = data["unit"]
        _type = data.get("type", None)
        if _type in (
            "PostMeterDataRequest",
            "PostPrognosisRequest",
        ) and not units_are_convertible(posted_unit, "MW"):
            raise ValidationError(
                f"The unit required for this message type should be convertible to MW, got incompatible unit: {posted_unit}"
            )
        elif _type == "PostPriceDataRequest" and not is_energy_price_unit(posted_unit):
            raise ValidationError(
                f"The unit required for this message type should be convertible to an energy price unit, got incompatible unit: {posted_unit}"
            )

    @validates_schema
    def check_resolution_compatibility_of_sensor_data(self, data, **kwargs):
        """Ensure event frequency is compatible with the sensor's event resolution.

        For a sensor recording instantaneous values, any event frequency is compatible.
        For a sensor recording non-instantaneous values, the event frequency must fit the sensor's event resolution.
        Currently, only upsampling is supported (e.g. converting hourly events to 15-minute events).
        """
        required_resolution = data["sensor"].event_resolution

        if required_resolution == timedelta(hours=0):
            # For instantaneous sensors, any event frequency is compatible
            return

        # The event frequency is inferred by assuming sequential, equidistant values within a time interval.
        # The event resolution is assumed to be equal to the event frequency.
        inferred_resolution = data["duration"] / len(data["values"])
        if inferred_resolution % required_resolution != timedelta(hours=0):
            raise ValidationError(
                f"Resolution of {inferred_resolution} is incompatible with the sensor's required resolution of {required_resolution}."
            )

    @validates_schema
    def check_multiple_instantenous_values(self, data, **kwargs):
        """Ensure that we are not getting multiple instantaneous values that overlap.
        That is, two values spanning the same moment (a zero duration).
        """

        if len(data["values"]) > 1 and data["duration"] / len(
            data["values"]
        ) == timedelta(0):
            raise ValidationError(
                "Cannot save multiple instantaneous values that overlap. That is, two values spanning the same moment (a zero duration). Try sending a single value or definining a non-zero duration."
            )

    @post_load()
    def post_load_sequence(self, data: dict, **kwargs) -> BeliefsDataFrame:
        """If needed, upsample and convert units, then deserialize to a BeliefsDataFrame."""
        data = self.possibly_upsample_values(data)
        data = self.possibly_convert_units(data)
        bdf = self.load_bdf(data)

        # Post-load validation against message type
        _type = data.get("type", None)
        if _type == "PostMeterDataRequest":
            if any(h > timedelta(0) for h in bdf.belief_horizons):
                raise ValidationError("Meter data must lie in the past.")
        elif _type == "PostPrognosisRequest":
            if any(h < timedelta(0) for h in bdf.belief_horizons):
                raise ValidationError("Prognoses must lie in the future.")

        return bdf

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
        required_resolution = data["sensor"].event_resolution
        if required_resolution == timedelta(hours=0):
            # For instantaneous sensors, no need to upsample
            return data

        # The event frequency is inferred by assuming sequential, equidistant values within a time interval.
        # The event resolution is assumed to be equal to the event frequency.
        inferred_resolution = data["duration"] / len(data["values"])

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
        source = get_or_create_source(current_user)
        num_values = len(sensor_data["values"])
        event_resolution = sensor_data["duration"] / num_values

        if event_resolution == timedelta(hours=0):
            dt_index = pd.date_range(
                sensor_data["start"],
                periods=num_values,
            )
        else:
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
        ).dropna()
