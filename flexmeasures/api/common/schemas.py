from typing import Union

from datetime import timedelta

from marshmallow import fields, ValidationError
import isodate
from isodate.isoerror import ISO8601Error


class PeriodField(fields.Str):
    """Field that serializes to a Period and deserializes to a string."""

    def _deserialize(
        self, value, attr, obj, **kwargs
    ) -> Union[timedelta, isodate.Duration]:
        return isodate.parse_duration(value)

    def _vaidate(value):
        """Validate a marshmallow ISO8601 duration field,
        throw marshmallow validation error if it cannot be parsed."""
        try:
            isodate.parse_duration(value)
        except ISO8601Error as iso_err:
            raise ValidationError(
                f"Cannot parse {value} as ISO8601 duration: {iso_err}"
            )

    def _serialize(self, value, attr, data, **kwargs):
        return isodate.strftime(value, "%P")
