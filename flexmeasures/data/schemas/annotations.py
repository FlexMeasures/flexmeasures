from __future__ import annotations

from marshmallow import Schema, fields, validates_schema, ValidationError
from marshmallow.validate import OneOf, Length

from flexmeasures.data.schemas.times import AwareDateTimeField
from flexmeasures.data.schemas.sources import DataSourceIdField


class AnnotationSchema(Schema):
    """Schema for annotation POST requests."""

    content = fields.Str(required=True, validate=Length(max=1024))
    start = AwareDateTimeField(required=True, format="iso")
    end = AwareDateTimeField(required=True, format="iso")
    type = fields.Str(
        required=False,
        load_default="label",
        validate=OneOf(["alert", "holiday", "label", "feedback", "warning", "error"]),
    )
    belief_time = AwareDateTimeField(required=False, allow_none=True, format="iso")

    @validates_schema
    def validate_time_range(self, data, **kwargs):
        """Validate that end is after start."""
        if "start" in data and "end" in data:
            if data["end"] <= data["start"]:
                raise ValidationError("end must be after start")


class AnnotationResponseSchema(Schema):
    """Schema for annotation API responses."""

    id = fields.Int(dump_only=True)
    content = fields.Str()
    start = AwareDateTimeField(format="iso")
    end = AwareDateTimeField(format="iso")
    type = fields.Str()
    belief_time = AwareDateTimeField(format="iso")
    source_id = fields.Int(dump_only=True)

    class Meta:
        ordered = True
