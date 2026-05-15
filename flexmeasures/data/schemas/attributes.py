from typing import Any
import json

from altair.vegalite.schema import Interpolate
from marshmallow import fields, ValidationError


class JSON(fields.Field):
    def _deserialize(self, value, attr, data, **kwargs):
        # Accept already-deserialized JSON values from request parsers.
        if isinstance(value, (dict, list, int, float, bool)) or value is None:
            return value

        # Backward-compatible path: allow JSON-encoded strings.
        if isinstance(value, (str, bytes, bytearray)):
            try:
                return json.loads(value)
            except ValueError:
                raise ValidationError("Not a valid JSON string.")

        raise ValidationError("Not a valid JSON value.")

    def _serialize(self, value, attr, obj, **kwargs) -> str:
        return json.dumps(value)


def validate_special_attributes(key: str, value: Any):
    """Validate attributes with a special meaning in FlexMeasures."""
    if key == "interpolate":
        Interpolate.validate(value)
