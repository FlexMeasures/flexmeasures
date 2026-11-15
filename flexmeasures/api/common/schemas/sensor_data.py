from __future__ import annotations

from datetime import datetime, timedelta

from flask import current_app
from flask_login import current_user
from isodate import datetime_isoformat
from marshmallow import (
    fields,
    post_load,
    pre_load,
    validates,
    validates_schema,
    ValidationError,
)
from marshmallow.validate import OneOf, Length
from marshmallow_polyfield import PolyField
from timely_beliefs import BeliefsDataFrame
import pandas as pd

from flexmeasures.data import ma
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import User
from flexmeasures.api.common.schemas.sensors import (
    SensorEntityAddressField,
    SensorIdField,
)
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.api.common.utils.api_utils import upsample_values
from flexmeasures.data.models.planning.utils import initialize_index
from flexmeasures.data.schemas import (
    AwareDateTimeField,
    DurationField,
    ResolutionField,
    SourceIdField,
)
from flexmeasures.data.services.data_sources import get_or_create_source
from flexmeasures.data.services.time_series import simplify_index
from flexmeasures.utils.recurrence import (
    RecurrenceError,
    RecurrenceReport,
    expand_wall_clock_recurrence,
)
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

    def _deserialize(self, value, attr, data, **kwargs) -> list[float]:
        return [self._validated(value)]

    def _serialize(self, value, attr, obj, **kwargs) -> list[float]:
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


class SensorDataTimingDescriptionSchema(ma.Schema):
    """
    Schema describing sensor data (specifically, the timing of the data).
    """

    start = AwareDateTimeField(
        required=True,
        format="iso",
        metadata=dict(
            description="Start time of the first event described in the time series data, in ISO 8601 datetime format.",
            example="2026-01-15T10:00+01:00",
        ),
    )
    duration = DurationField(
        required=True,
        metadata=dict(
            description="Duration of the full set of events described in the time series data, in ISO 8601 duration format.",
            example="PT1H",
        ),
    )
    horizon = DurationField(
        required=False,
        metadata=dict(
            description="All sensor data has been recorded at least this duration beforehand (for physical event, before the event ended; for economical events, before gate closure).",
            example="PT2H",
        ),
    )
    prior = AwareDateTimeField(
        required=False,
        format="iso",
        metadata=dict(
            description="All sensor data has been recorded prior to this [belief time](https://flexmeasures.readthedocs.io/latest/concepts/time-series-and-beliefs.html#beliefs-and-their-recording-time).",
            example="2026-01-14T20:00+01:00",
        ),
    )
    unit = fields.Str(
        required=True,
        metadata=dict(
            description="The unit of the sensor data, which must be convertible to the sensor unit.",
            example="m³/h",
        ),
    )


class SensorDataDescriptionSchema(SensorDataTimingDescriptionSchema):
    """
    Schema describing sensor data (specifically, adding the sensor to timing of the data
    and adding validation).
    """

    sensor = SensorIdField(
        required=True,
        metadata=dict(
            description="ID of the sensor on which the data is recorded.",
            example=14,
        ),
    )

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


class GetSensorDataFilterSchemaMixin:
    """Shared filters for GET sensor data request parsing and docs."""

    resolution = ResolutionField(
        required=False,
        metadata=dict(
            description="Resolution of the returned sensor data in ISO 8601 duration format.",
            example="PT15M",
        ),
    )
    source = SourceIdField(
        required=False,
        metadata=dict(
            description="Filter by a specific data source ID.",
            example=42,
        ),
    )
    source_account = AccountIdField(
        data_key="source-account",
        required=False,
        metadata=dict(
            description="Filter by the account linked to data sources.",
            example=3,
        ),
    )
    source_type = fields.Str(
        data_key="source-type",
        required=False,
        validate=Length(min=1),
        metadata=dict(
            description="Filter by a specific data source type.",
            example="forecaster",
        ),
    )

    @pre_load
    def support_legacy_field_name(self, data, **kwargs):
        """Accept old snake_case input for backwards compatibility."""
        return {key.replace("_", "-"): value for key, value in data.items()}


class GetSensorDataSchema(GetSensorDataFilterSchemaMixin, SensorDataDescriptionSchema):

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

    @validates_schema
    def source_type_must_exist_on_sensor(self, data, **kwargs):
        source_type = data.get("source_type")
        if not source_type:
            return
        sensor: Sensor = data["sensor"]
        if not sensor.search_data_sources(
            source_types=[source_type], check_exists=True
        ):
            raise ValidationError(
                f"No data source with source-type '{source_type}' has recorded any data on this sensor.",
                field_name="source_type",
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
        source_account = sensor_data_description.get("source_account")
        source_type = sensor_data_description.get("source_type")

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
                source_account_ids=source_account.id if source_account else None,
                source_types=[source_type] if source_type else None,
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


class GetSensorDataQuerySchema(
    GetSensorDataFilterSchemaMixin, SensorDataTimingDescriptionSchema
):
    """Document the actual query parameters for GET /sensors/<id>/data."""


class PostSensorDataSchema(SensorDataDescriptionSchema):
    """
    This schema includes data (values) and still describes it.
    """

    def __init__(self, *args, source_user: User | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_user = source_user

    values = PolyField(
        deserialization_schema_selector=select_schema_to_ensure_list_of_floats,
        serialization_schema_selector=select_schema_to_ensure_list_of_floats,
        many=False,
        metadata=dict(
            description="The event values.",
            example=[2.2, 2.6, 2.6, 2.7],
        ),
    )

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
        metadata=dict(
            description="Obsolete message type from [<abbr title='Universal Smart Energy Framework'>USEF</abbr>](https://www.usef.energy/).",
        ),
    )
    repeat = fields.Str(
        required=False,
        validate=OneOf(["daily", "same-weekday", "workdays", "weekends"]),
        metadata=dict(
            description=(
                "Repeat the values every day, every 7 days (on the same weekday only), on workdays (Monday to Friday), "
                "or on weekends (Saturday and Sunday), at the same local time in the sensor's timezone, until the date given by `until`. "
                "The values are then a pattern of at most one day (or one week, for `same-weekday`)."
            ),
            example="daily",
        ),
    )
    until = fields.Date(
        required=False,
        metadata=dict(
            description="With `repeat`: the last date to repeat the values on, inclusive, in the sensor's timezone. At most one year after the values start.",
            example="2026-11-30",
        ),
    )

    @validates_schema
    def check_repeat_and_until_go_together(self, data, **kwargs):
        if ("repeat" in data) != ("until" in data):
            raise ValidationError(
                "Give both `repeat` and `until` to repeat the values, or neither."
            )

    @validates("duration")
    def check_duration_is_exact(self, duration, **kwargs):
        """Refuse a calendar duration (such as P1M), whose length depends on when it starts, before the resolution checks divide it."""
        if not isinstance(duration, timedelta):
            raise ValidationError(
                "Give the duration in weeks, days, hours or minutes (such as P1D), rather than in months or years."
            )

    @validates_schema
    def check_pattern_can_be_repeated(self, data, **kwargs):
        """Check a pattern to repeat: a sensor with a resolution, no finer values than the sensor's, and at most a year of repeats."""
        if "repeat" not in data or "until" not in data:
            return
        sensor = data["sensor"]
        if sensor.event_resolution == timedelta(0):
            raise ValidationError(
                "Repeating values is not supported for a sensor that records instantaneous values."
            )
        inferred_resolution = data["duration"] / len(data["values"])
        if inferred_resolution < sensor.event_resolution:
            raise ValidationError(
                f"Send the values to repeat at the sensor's resolution of {duration_isoformat(sensor.event_resolution)} or coarser, "
                f"rather than at {duration_isoformat(inferred_resolution)}."
            )
        local_start = pd.Timestamp(data["start"]).tz_convert(sensor.timezone)
        last_date = (
            local_start.tz_localize(None).normalize() + pd.DateOffset(years=1)
        ).date()
        if data["until"] > last_date:
            raise ValidationError(
                f"Repeat until {last_date.isoformat()} at the latest, which is one year after the values start; send longer ranges in parts.",
                field_name="until",
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
    def check_single_value_zero_duration_for_non_instantaneous_sensor(
        self, data, **kwargs
    ):
        """Reject inputs where a non-instantaneous sensor cannot infer any resolution."""

        required_resolution = data["sensor"].event_resolution
        inferred_resolution = data["duration"] / len(data["values"])

        if (
            required_resolution != timedelta(hours=0)
            and len(data["values"]) == 1
            and inferred_resolution == timedelta(hours=0)
        ):
            raise ValidationError(
                f"Cannot infer a non-zero resolution from one value over zero duration. This sensor requires a resolution of {required_resolution}."
            )

    @validates_schema
    def check_resolution_compatibility_of_sensor_data(self, data, **kwargs):
        """Ensure event frequency is compatible with the sensor's event resolution.

        For a sensor recording instantaneous values, any event frequency is compatible.
        For a sensor recording non-instantaneous values, the event frequency must fit the sensor's event resolution.
        Upsampling and downsampling are supported when the inferred resolution and
        the sensor resolution are multiples of each other.
        """
        required_resolution = data["sensor"].event_resolution

        if required_resolution == timedelta(hours=0):
            # For instantaneous sensors, any event frequency is compatible
            return

        # The event frequency is inferred by assuming sequential, equidistant values within a time interval.
        # The event resolution is assumed to be equal to the event frequency.
        inferred_resolution = data["duration"] / len(data["values"])
        if inferred_resolution % required_resolution != timedelta(
            hours=0
        ) and required_resolution % inferred_resolution != timedelta(hours=0):
            raise ValidationError(
                f"Resolution of {inferred_resolution} is incompatible with the sensor's required resolution of {required_resolution}."
            )

    @validates_schema
    def check_multiple_instantaneous_values(self, data, **kwargs):
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
    def post_load_sequence(self, data: dict, **kwargs) -> dict[str, BeliefsDataFrame]:
        """
        If needed, upsample and convert units, then deserialize to a BeliefsDataFrame.
        Returns a dict with the BDF in it, as that is expected by webargs when used with as_kwargs=True.
        """
        data = self.possibly_upsample_values(data)
        data = self.possibly_convert_units(data)
        if "repeat" in data:
            values, _ = self.expand_repeat(data)
            bdf = self.make_bdf(
                values.dropna(), data, event_resolution=data["sensor"].event_resolution
            )
        else:
            bdf = self.load_bdf(data)
            bdf = self.possibly_downsample_bdf(bdf, data["sensor"].event_resolution)

        # Post-load validation against message type
        _type = data.get("type", None)
        if _type == "PostMeterDataRequest":
            if any(h > timedelta(0) for h in bdf.belief_horizons):
                raise ValidationError("Meter data must lie in the past.")
        elif _type == "PostPrognosisRequest":
            if any(h < timedelta(0) for h in bdf.belief_horizons):
                raise ValidationError("Prognoses must lie in the future.")

        return dict(bdf=bdf)

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
            event_resolution=data["duration"] / len(data["values"]),
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
    def possibly_downsample_bdf(
        bdf: BeliefsDataFrame, required_resolution: timedelta
    ) -> BeliefsDataFrame:
        """
        Downsample the data if needed, to fit the sensor's resolution.
        Marshmallow runs this after validation.
        """
        if required_resolution == timedelta(hours=0):
            return bdf

        if bdf.event_resolution < required_resolution:
            bdf = bdf.resample_events(required_resolution)
        return bdf

    @staticmethod
    def expand_repeat(data: dict) -> tuple[pd.Series, RecurrenceReport]:
        """Repeat the (upsampled) values as asked by `repeat` and `until`, starting with the values themselves.

        The values themselves are left out only if the repeat days leave out the day they start on, such as a Saturday repeated on workdays.
        Returns the values with NaN where there is no value, indexed by event start in the sensor's timezone, and a report of what clock changes did to them.

        :raises ValidationError: if the values cannot be repeated as asked, or would repeat to more values than allowed.
        """
        sensor = data["sensor"]
        start = PostSensorDataSchema.align_start_to_sensor(data["start"], sensor)
        pattern = pd.Series(
            data["values"],
            index=pd.date_range(
                start, periods=len(data["values"]), freq=sensor.event_resolution
            ),
            dtype=float,
        )
        on_days = {
            "workdays": lambda day: day.weekday() < 5,
            "weekends": lambda day: day.weekday() >= 5,
        }.get(data["repeat"])
        try:
            values, report = expand_wall_clock_recurrence(
                pattern,
                until=data["until"],
                tz=sensor.timezone,
                resolution=sensor.event_resolution,
                same_weekday_only=data["repeat"] == "same-weekday",
                on_days=on_days,
                include_pattern=True,
            )
        except RecurrenceError as exc:
            raise ValidationError(str(exc)) from exc
        n_values = int(values.notna().sum())
        if n_values == 0:
            raise ValidationError(
                f"The values are not repeated on any day until {data['until'].isoformat()}; repeat them until a later date, or on other days."
            )
        max_values = current_app.config.get("FLEXMEASURES_MAX_REPEATED_SENSOR_VALUES")
        if max_values is not None and n_values > max_values:
            raise ValidationError(
                f"Repeating gives {n_values} values, more than the maximum of {max_values}; repeat until an earlier date, and send the rest in another request.",
                field_name="until",
            )
        return values, report

    @staticmethod
    def align_start_to_sensor(start: datetime, sensor: Sensor) -> datetime:
        """Align the start of posted data to the sensor's grid of events, as configured on the sensor.

        By default, the start is floored to the sensor resolution;
        an instantaneous sensor may instead round it to its configured frequency.
        """
        if sensor.event_resolution != timedelta(0) and sensor.get_attribute(
            "floor_datetimes_to_resolution", True
        ):
            return pd.Timestamp(start).floor(sensor.event_resolution)
        elif frequency := sensor.get_attribute("frequency"):
            return pd.Timestamp(start).round(frequency)
        return start

    def load_bdf(self, sensor_data: dict) -> BeliefsDataFrame:
        """
        Turn the de-serialized and validated data into a BeliefsDataFrame.
        """
        num_values = len(sensor_data["values"])
        event_resolution = sensor_data["duration"] / num_values
        start = self.align_start_to_sensor(sensor_data["start"], sensor_data["sensor"])

        if event_resolution == timedelta(hours=0):
            dt_index = pd.date_range(
                start,
                periods=num_values,
            )
        else:
            dt_index = pd.date_range(
                start,
                periods=num_values,
                freq=event_resolution,
            )
        s = pd.Series(sensor_data["values"], index=dt_index)
        return self.make_bdf(s, sensor_data, event_resolution=event_resolution)

    def make_bdf(
        self, s: pd.Series, sensor_data: dict, event_resolution: timedelta
    ) -> BeliefsDataFrame:
        """Turn values indexed by event start into beliefs of the posting user, timed as the sensor data says."""
        source = get_or_create_source(self.source_user or current_user)

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
            event_resolution=event_resolution,
            **belief_timing,
        )


class PostSensorDataRequestSchema(PostSensorDataSchema):
    """Validate posted sensor data without building a BeliefsDataFrame.

    Values to repeat are expanded here too, for the report in the response, and for a dry run;
    the values are saved from the serialized sensor data, which expands them again in the same way.
    """

    dry_run = fields.Boolean(
        data_key="dry-run",
        required=False,
        load_default=False,
        metadata=dict(
            description=(
                "Only check the data and say what would be saved, without saving anything. "
                "A dry run is answered directly, rather than as a job."
            ),
            example=True,
        ),
    )

    @post_load()
    def post_load_sequence(self, data: dict, **kwargs) -> dict:
        dry_run = data.pop("dry_run", False)
        recurrence = None
        if "repeat" in data or dry_run:
            # The values in the posted unit, as they would be saved (before unit conversion).
            expansion_data = self.possibly_upsample_values(dict(data))
            if "repeat" in expansion_data:
                values, report = self.expand_repeat(expansion_data)
            else:
                values, report = self.lay_out_values(expansion_data), None
            recurrence = dict(values=values, report=report)
        sensor_data = {
            "values": data["values"],
            "start": datetime_isoformat(data["start"]),
            "duration": duration_isoformat(data["duration"]),
            "unit": data["unit"],
        }
        if "prior" in data:
            sensor_data["prior"] = datetime_isoformat(data["prior"])
        elif "horizon" in data:
            sensor_data["horizon"] = duration_isoformat(data["horizon"])
        else:
            # Preserve request-time semantics when processing happens later in a worker.
            sensor_data["prior"] = datetime_isoformat(server_now())
        if "type" in data:
            sensor_data["type"] = data["type"]
        if "repeat" in data:
            sensor_data["repeat"] = data["repeat"]
            sensor_data["until"] = data["until"].isoformat()
        return dict(
            sensor=data["sensor"],
            sensor_data=sensor_data,
            dry_run=dry_run,
            expanded=recurrence,
        )

    @staticmethod
    def lay_out_values(data: dict) -> pd.Series:
        """Index the (upsampled) values by event start, as they would be saved without repeating them."""
        sensor = data["sensor"]
        start = PostSensorDataSchema.align_start_to_sensor(data["start"], sensor)
        resolution = data["duration"] / len(data["values"])
        index = (
            pd.date_range(start, periods=len(data["values"]), freq=resolution)
            if resolution > timedelta(0)
            else pd.DatetimeIndex([start] * len(data["values"]))
        )
        return pd.Series(data["values"], index=index, dtype=float)


class GetSensorDataSchemaEntityAddress(GetSensorDataSchema):
    """DEPRECATED, only here to support deprecated endpoints"""

    sensor = SensorEntityAddressField(
        required=True, entity_type="sensor", fm_scheme="fm1"
    )


class PostSensorDataSchemaEntityAddress(PostSensorDataSchema):
    """DEPRECATED, only here to support deprecated endpoints"""

    sensor = SensorEntityAddressField(
        required=True, entity_type="sensor", fm_scheme="fm1"
    )
