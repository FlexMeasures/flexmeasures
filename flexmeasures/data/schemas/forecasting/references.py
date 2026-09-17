from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from marshmallow import fields, post_dump, validate, validates_schema, ValidationError

from flexmeasures.data.models.forecasting.utils import _is_parseable_quantity
from flexmeasures.data.schemas.sensors import (
    SENSOR_REFERENCE_SOURCE_FILTER_KEYS,
    SensorIdOrReferenceField,
    SensorReference,
    SensorReferenceSchema,
)

#: The keys that carry cleaning bounds on a forecaster input reference.
FORECAST_INPUT_BOUND_KEYS = frozenset({"lower", "upper", "snap"})


@dataclass
class ForecastInputReference(SensorReference):
    """A sensor reference for a forecaster input, carrying optional cleaning bounds.

    Values read from the sensor are snapped and clipped to these bounds before the model trains on them,
    so that a sensor with implausible readings can be cleaned up without touching the stored data.
    The bounds are separate from the forecaster's ``lower``, ``upper`` and ``snap`` config,
    which shape the forecast on its way out rather than the training data on its way in.
    """

    lower: Any = field(default=None)
    upper: Any = field(default=None)
    snap: dict = field(default_factory=dict)

    @property
    def has_bounds(self) -> bool:
        """Whether this reference asks for any cleaning at all."""
        return self.lower is not None or self.upper is not None or bool(self.snap)


class ForecastInputReferenceSchema(SensorReferenceSchema):
    """Sensor reference for a forecaster input, with optional source filters and cleaning bounds.

    The bounds live here rather than on the shared sensor reference, because they mean nothing to the flex-model and flex-context fields that share that schema.
    """

    class Meta:
        description = "Sensor reference a forecaster reads an input from."

    lower = fields.Raw(
        required=False,
        allow_none=True,
        load_default=None,
        metadata={
            "description": "Optional lower bound for values read from this sensor, applied after gaps are filled. Unitless values are interpreted in the sensor's own unit.",
            "example": "0 kW",
        },
    )
    upper = fields.Raw(
        required=False,
        allow_none=True,
        load_default=None,
        metadata={
            "description": "Optional upper bound for values read from this sensor, applied after gaps are filled. Unitless values are interpreted in the sensor's own unit.",
            "example": "20 kW",
        },
    )
    snap = fields.Dict(
        keys=fields.Raw(),
        values=fields.List(fields.Raw(), validate=validate.Length(equal=2)),
        required=False,
        load_default={},
        metadata={
            "description": "Optional mapping from snap targets to [first, second] intervals, applied to values read from this sensor. The target must lie within the interval. The first bound is inclusive and the second exclusive, so [first, second) by default; reverse the order to close the upper side instead.",
            "example": {"0 kW": ["0 kW", "0.5 kW"]},
        },
    )

    @post_dump
    def remove_empty_bounds(self, data, **kwargs):
        """Omit bounds that carry nothing, so a reference without cleaning serialises exactly as it did before.

        A zero bound is meaningful, so only None and an empty snap mapping are dropped.
        """
        for field_name in ("lower", "upper"):
            if data.get(field_name) is None:
                data.pop(field_name, None)
        if not data.get("snap"):
            data.pop("snap", None)
        return data

    @validates_schema
    def validate_bounds(self, data: dict, **kwargs):
        """Fail fast on unparseable bounds.

        Unit compatibility with the sensor and interval semantics can only be checked once the data is read, so those run at forecast time.
        """
        errors: dict[str, list[str]] = {}
        for field_name in ("lower", "upper"):
            value = data.get(field_name)
            if value is not None and not _is_parseable_quantity(value):
                errors[field_name] = [
                    "Must be a number or a parseable quantity string (e.g. 0 or '0 kW')."
                ]

        snap_errors = [
            f"Snap entry '{target}' must use numbers or parseable quantity strings."
            for target, interval in (data.get("snap") or {}).items()
            if not all(_is_parseable_quantity(v) for v in (target, *interval))
        ]
        if snap_errors:
            errors["snap"] = snap_errors

        if errors:
            raise ValidationError(errors)


class ForecastInputField(SensorIdOrReferenceField):
    """Field accepting a sensor ID, or a reference that may carry source filters and cleaning bounds."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sensor_reference_schema = ForecastInputReferenceSchema()

    def _deserialize(self, value: Any, attr, data, **kwargs):
        if not isinstance(value, dict):
            return self.sensor_id_field.deserialize(value, attr, data, **kwargs)

        sensor_reference = self.sensor_reference_schema.load(value)
        # A bare sensor is enough unless the reference asks for filtering or cleaning.
        if SENSOR_REFERENCE_SOURCE_FILTER_KEYS.isdisjoint(
            value
        ) and FORECAST_INPUT_BOUND_KEYS.isdisjoint(value):
            return sensor_reference["sensor"]
        return ForecastInputReference(**sensor_reference)
