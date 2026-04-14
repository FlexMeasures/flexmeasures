from typing import Any
import json

from altair.vegalite.schema import Interpolate
from marshmallow import fields, ValidationError


class JSON(fields.Field):
    def _deserialize(self, value, attr, data, **kwargs) -> dict:
        try:
            return json.loads(value)
        except ValueError:
            raise ValidationError("Not a valid JSON string.")

    def _serialize(self, value, attr, obj, **kwargs) -> str:
        return json.dumps(value)


def validate_special_attributes(key: str, value: Any):
    """Validate attributes with a special meaning in FlexMeasures."""
    if key == "interpolate":
        Interpolate.validate(value)
