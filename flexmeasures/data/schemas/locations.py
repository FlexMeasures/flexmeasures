from __future__ import annotations

from marshmallow import ValidationError, fields, validate

from flexmeasures.data.schemas.utils import FMValidationError, MarshmallowClickMixin


class LatitudeLongitudeValidator(validate.Validator):
    """Validator which succeeds if the value passed has at most 7 decimal places."""

    def __init__(self, *, error: str | None = None):
        self.error = error

    def __call__(self, value):
        if not round(value, 7) == value:
            raise FMValidationError(
                "Latitudes and longitudes are limited to 7 decimal places."
            )
        return value


class LatitudeValidator(validate.Validator):
    """Validator which succeeds if the value passed is in the range [-90, 90]."""

    def __init__(self, *, error: str | None = None, allow_none: bool = False):
        self.error = error
        self.allow_none = allow_none

    def __call__(self, value):
        if self.allow_none and value is None:
            return
        if value < -90:
            raise FMValidationError(
                f"Latitude {value} exceeds the minimum latitude of -90 degrees."
            )
        if value > 90:
            raise ValidationError(
                f"Latitude {value} exceeds the maximum latitude of 90 degrees."
            )
        return value


class LongitudeValidator(validate.Validator):
    """Validator which succeeds if the value passed is in the range [-180, 180]."""

    def __init__(self, *, error: str | None = None, allow_none: bool = False):
        self.error = error
        self.allow_none = allow_none

    def __call__(self, value):
        if self.allow_none and value is None:
            return
        if value < -180:
            raise FMValidationError(
                f"Longitude {value} exceeds the minimum longitude of -180 degrees."
            )
        if value > 180:
            raise ValidationError(
                f"Longitude {value} exceeds the maximum longitude of 180 degrees."
            )
        return value


class LatitudeField(MarshmallowClickMixin, fields.Float):
    """Field that deserializes to a latitude float with max 7 decimal places."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Insert validation into self.validators so that multiple errors can be stored.
        self.validators.insert(0, LatitudeLongitudeValidator())
        self.validators.insert(
            0, LatitudeValidator(allow_none=kwargs.get("allow_none", False))
        )


class LongitudeField(MarshmallowClickMixin, fields.Float):
    """Field that deserializes to a longitude float with max 7 decimal places."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Insert validation into self.validators so that multiple errors can be stored.
        self.validators.insert(0, LatitudeLongitudeValidator())
        self.validators.insert(
            0, LongitudeValidator(allow_none=kwargs.get("allow_none", False))
        )
