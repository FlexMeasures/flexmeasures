from __future__ import annotations

from marshmallow import Schema, fields, validates_schema, ValidationError
from marshmallow.validate import OneOf

from flexmeasures.data.schemas.times import AwareDateTimeField


class AnnotationSchema(Schema):
    """Schema for annotation POST requests."""
    
    content = fields.Str(required=True, validate=lambda s: len(s) <= 1024)
    start = AwareDateTimeField(required=True, format="iso")
    end = AwareDateTimeField(required=True, format="iso")
    type = fields.Str(
        required=False,
        load_default="label",
        validate=OneOf(["alert", "holiday", "label", "feedback", "warning", "error"])
    )
    belief_time = AwareDateTimeField(required=False, allow_none=True, format="iso")
    
    @validates_schema
    def validate_time_range(self, data, **kwargs):
        """Validate that end is after start."""
        if "start" in data and "end" in data:
            if data["end"] <= data["start"]:
                raise ValidationError("end must be after start")
