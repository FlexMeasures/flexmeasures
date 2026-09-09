from __future__ import annotations

import json
from datetime import datetime, timedelta

from flask import current_app
from marshmallow import fields, Schema, validates_schema
from marshmallow.exceptions import ValidationError
import isodate
from isodate.isoduration import ISO8601_PERIOD_REGEX
from isodate.isoerror import ISO8601Error
import pandas as pd
from pytz.exceptions import UnknownTimeZoneError

from flexmeasures.data.schemas.utils import FMValidationError, MarshmallowClickMixin


class DurationValidationError(FMValidationError):
    status = "INVALID_PERIOD"  # USEF error status


class DurationField(MarshmallowClickMixin, fields.Str):
    """Field that deserializes to a ISO8601 Duration
    and serializes back to a string."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Define the string format for OpenAPI
        # The duration notation as defined by [RFC 3339, appendix A](https://tools.ietf.org/html/rfc3339#appendix-A), for example, PT24H
        if not self.metadata:
            self.metadata = {}
        self.metadata["format"] = "duration"

    def _deserialize(self, value, attr, data, **kwargs) -> timedelta | isodate.Duration:
        """
        Use the isodate library to turn an ISO8601 string into a timedelta.
        For some non-obvious cases, it will become an isodate.Duration, see
        ground_from for more.
        This method throws a ValidationError if the string is not ISO norm.
        """
        try:
            duration_value = isodate.parse_duration(value)
        except ISO8601Error as iso_err:
            raise DurationValidationError(
                f"Cannot parse {value} as ISO8601 duration: {iso_err}"
            )
        if duration_value.seconds % 60 != 0 or duration_value.microseconds != 0:
            raise DurationValidationError(
                "FlexMeasures only support multiples of 1 minute."
            )
        return duration_value

    def _serialize(self, value, attr, obj, **kwargs):
        """
        An implementation of _serialize.
        It is not guaranteed to return the same string as was input,
        if ground_from has been used!
        """
        return isodate.strftime(value, "P%P")

    @staticmethod
    def ground_from(
        duration: timedelta | isodate.Duration | pd.DateOffset,
        start: datetime | None,
        timezone: str | None = None,
    ) -> timedelta:
        """
        For some valid duration strings (such as "P1M", a month, or "P1D", a calendar day),
        converting to a datetime.timedelta is not possible (no obvious
        number of hours). In that case, `_deserialize` returned an
        `isodate.Duration` or a `pandas.DateOffset`. We can derive the timedelta by grounding to an
        actual time span, for which we require a timezone-aware start datetime.

        Pass a `timezone` (an IANA name, such as "Europe/Amsterdam") to say which calendar to count in.
        This matters: a start datetime parsed from an ISO 8601 string carries a fixed UTC offset rather than a zone,
        and a fixed offset never shifts, so counting against it would make every calendar day 24 hours long.
        Without a timezone, the start is used as it comes.
        """
        if isinstance(duration, (isodate.Duration, pd.DateOffset)) and start:
            if isinstance(duration, isodate.Duration):
                offset = pd.DateOffset(
                    years=duration.years,
                    months=duration.months,
                    days=duration.days,
                    seconds=duration.tdelta.seconds,
                )
            else:
                offset = duration
            anchor = pd.Timestamp(start)
            if timezone is not None and anchor.tzinfo is not None:
                try:
                    anchor = anchor.tz_convert(timezone)
                except UnknownTimeZoneError:
                    # fall back to counting against whatever the start datetime carries
                    pass
            return (anchor + offset).to_pydatetime() - start
        return duration


class NominalDurationField(DurationField):
    """Field for a duration that spans a window, and so is counted against the calendar.

    ISO 8601 tells calendar spans and fixed spans apart, and so does this field:
    "P1D" is one calendar day, which lasts 23 or 25 hours across a daylight saving time transition,
    while "PT24H" is always exactly 24 hours.
    A plain DurationField collapses both into 24 hours.
    That is what most settings want (a training period, a staleness threshold, a retry frequency),
    but not what a window wants: asking for "P1D" of data means asking for a day of the sensor's calendar.

    A value carrying years, months, weeks or days therefore deserializes to a pandas DateOffset,
    which keeps its calendar parts apart from its fixed parts.
    Ground it with `DurationField.ground_from` before using it as a timedelta,
    passing the timezone whose calendar to count in, usually the sensor's.
    Note that isodate cannot draw this distinction itself:
    with `as_timedelta_if_possible=False` it reports both "P1D" and "PT24H" as one day,
    see https://github.com/gweis/isodate/issues/74.
    """

    #: The ISO 8601 components that are counted in calendar units rather than in fixed time.
    nominal_components = ("years", "months", "weeks", "days")

    def _deserialize(self, value, attr, data, **kwargs) -> timedelta | pd.DateOffset:
        """Deserialize to a DateOffset if the duration spans calendar units, else to a timedelta."""
        # Run DurationField's parsing first, so that we accept and reject exactly what it does.
        duration = super()._deserialize(value, attr, data, **kwargs)
        match = ISO8601_PERIOD_REGEX.match(value)
        if match is None:
            # The alternative "P<datetime>" format, which DurationField parses separately.
            return duration
        groups = match.groupdict()
        nominal = {
            name: float(groups[name][:-1])
            for name in self.nominal_components
            if groups.get(name) is not None
        }
        if not any(nominal.values()):
            return duration
        if any(amount != int(amount) for amount in nominal.values()):
            # A fraction of a calendar unit has no calendar meaning, so read the whole duration as fixed time.
            return duration
        # Every remaining component is a fixed amount of time, which is unambiguous in seconds.
        fixed_seconds = sum(
            float(groups[name][:-1]) * unit_seconds
            for name, unit_seconds in (("hours", 3600), ("minutes", 60), ("seconds", 1))
            if groups.get(name) is not None
        )
        offset = pd.DateOffset(
            **{name: int(amount) for name, amount in nominal.items()},
            seconds=fixed_seconds,
        )
        return -offset if groups.get("sign") == "-" else offset


class ResolutionField(DurationField):
    """Field that deserializes to an ISO8601 Duration to be used as a resolution.

    On top of what DurationField accepts, a resolution must span a positive amount of time.
    A zero resolution describes no event frequency at all,
    and a negative resolution describes events going back in time,
    neither of which can be turned into a series of events.
    """

    def _deserialize(self, value, attr, data, **kwargs) -> timedelta | isodate.Duration:
        duration_value = super()._deserialize(value, attr, data, **kwargs)
        if not _spans_positive_time(duration_value):
            raise DurationValidationError(
                f"FlexMeasures only supports a positive resolution, got: {value}."
            )
        return duration_value


def _spans_positive_time(duration: timedelta | isodate.Duration) -> bool:
    """Whether the given duration spans a positive amount of time.

    Nominal durations (such as "P1M") are not grounded to an actual time span here,
    because their sign does not depend on the time span they are grounded to.
    Only years and months sit outside an isodate.Duration's tdelta;
    its days and seconds are held by that tdelta, so checking it covers them both.
    """
    if isinstance(duration, isodate.Duration):
        return (
            duration.years > 0 or duration.months > 0 or duration.tdelta > timedelta(0)
        )
    return duration > timedelta(0)


class PlanningDurationField(DurationField):
    @classmethod
    def load_default(cls):
        """
        Use this with the load_default arg to __init__ if you want the default FlexMeasures planning horizon.
        """
        return current_app.config.get("FLEXMEASURES_PLANNING_HORIZON")


class AwareDateTimeField(MarshmallowClickMixin, fields.AwareDateTime):
    """Field that de-serializes to a timezone aware datetime
    and serializes back to a string."""

    def _deserialize(self, value: str, attr, data, **kwargs) -> datetime:
        """
        Work-around until this PR lands:
        https://github.com/marshmallow-code/marshmallow/pull/1787
        """
        value = value.replace(" ", "+")
        return super()._deserialize(value, attr, data, **kwargs)


class AwareDateTimeOrDateField(AwareDateTimeField):
    """Like AwareDateTimeField, but accepts naive dates, which are localized to the FLEXMEASURES_TIMEZONE.

    If inclusive=False (the default), converts dates to (midnight at) the start of the day.
    Otherwise, if inclusive=True, converts dates to (midnight at) the end of the day.
    """

    def __init__(self, inclusive: bool = False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inclusive = inclusive

    def _deserialize(self, value: str, attr, data, **kwargs) -> datetime:
        """Try deserializing a naive date (ISO 8601) before falling back to an aware datetime."""
        try:
            dt = datetime.strptime(value, "%Y-%m-%d")
            timezone = current_app.config.get("FLEXMEASURES_TIMEZONE")
            dt_aware = pd.Timestamp(dt).tz_localize(timezone)
            if self.inclusive:
                return dt_aware + pd.DateOffset(days=1)
            return dt_aware
        except ValueError:
            return super()._deserialize(value, attr, data, **kwargs)


class TimeIntervalSchema(Schema):
    start = AwareDateTimeField(required=True)
    duration = DurationField(required=True)


class TimeIntervalField(MarshmallowClickMixin, fields.Dict):
    """Field that de-serializes to a TimeInterval defined with start and duration."""

    def _deserialize(self, value: str, attr, data, **kwargs) -> dict:
        try:
            v = json.loads(value)
        except json.JSONDecodeError:
            raise ValidationError()

        return TimeIntervalSchema().load(v)


class StartEndTimeSchema(Schema):
    start_time = AwareDateTimeField(required=False)
    end_time = AwareDateTimeField(required=False)

    @validates_schema
    def validate(self, data, **kwargs):
        if not (data.get("start_time") or data.get("end_time")):
            return
        if not (data.get("start_time") and data.get("end_time")):
            raise ValidationError(
                "Both start_time and end_time must be provided together."
            )
        if data["start_time"] >= data["end_time"]:
            raise ValidationError("start_time must be before end_time.")
