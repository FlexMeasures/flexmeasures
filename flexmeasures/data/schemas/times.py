from __future__ import annotations

import json
from datetime import datetime, timedelta

from flask import current_app
from marshmallow import fields, Schema, validates_schema
from marshmallow.exceptions import ValidationError
import isodate
from isodate.isoerror import ISO8601Error
import pandas as pd

from flexmeasures.data.schemas.utils import FMValidationError, MarshmallowClickMixin


class DurationValidationError(FMValidationError):
    status = "INVALID_PERIOD"  # USEF error status


class DurationField(MarshmallowClickMixin, fields.Str):
    """Field that deserializes to a ISO8601 Duration
    and serializes back to a string."""

    def _deserialize(self, value, attr, obj, **kwargs) -> timedelta | isodate.Duration:
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

    def _serialize(self, value, attr, data, **kwargs):
        """
        An implementation of _serialize.
        It is not guaranteed to return the same string as was input,
        if ground_from has been used!
        """
        return isodate.strftime(value, "P%P")

    @staticmethod
    def ground_from(
        duration: timedelta | isodate.Duration, start: datetime | None
    ) -> timedelta:
        """
        For some valid duration strings (such as "P1M", a month),
        converting to a datetime.timedelta is not possible (no obvious
        number of days). In this case, `_deserialize` returned an
        `isodate.Duration`. We can derive the timedelta by grounding to an
        actual time span, for which we require a timezone-aware start datetime.
        """
        if isinstance(duration, isodate.Duration) and start:
            years = duration.years
            months = duration.months
            days = duration.days
            seconds = duration.tdelta.seconds
            offset = pd.DateOffset(
                years=years, months=months, days=days, seconds=seconds
            )
            return (pd.Timestamp(start) + offset).to_pydatetime() - start
        return duration


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

    def _deserialize(self, value: str, attr, obj, **kwargs) -> datetime:
        """
        Work-around until this PR lands:
        https://github.com/marshmallow-code/marshmallow/pull/1787
        """
        value = value.replace(" ", "+")
        return fields.AwareDateTime._deserialize(self, value, attr, obj, **kwargs)


class TimeIntervalSchema(Schema):
    start = AwareDateTimeField(required=True)
    duration = DurationField(required=True)


class TimeIntervalField(MarshmallowClickMixin, fields.Dict):
    """Field that de-serializes to a TimeInverval defined with start and duration."""

    def _deserialize(self, value: str, attr, obj, **kwargs) -> dict:
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
