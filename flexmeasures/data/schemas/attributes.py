from typing import Any

from altair.vegalite.schema import Interpolate


def validate_special_attributes(key: str, value: Any):
    """Validate attributes with a special meaning in FlexMeasures."""
    if key == "interpolate":
        Interpolate.validate(value)
