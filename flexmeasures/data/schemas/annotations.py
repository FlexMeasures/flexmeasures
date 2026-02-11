from __future__ import annotations

from marshmallow import Schema, fields, validates_schema, ValidationError
from marshmallow.validate import OneOf, Length

from flexmeasures.data.schemas.times import AwareDateTimeField


class AnnotationSchema(Schema):
    """Schema for annotation POST requests."""

    id = fields.Int(
        dump_only=True,
        metadata=dict(
            description="The annotation's ID, which is automatically assigned.",
            example=19,
        ),
    )
    source_id = fields.Int(
        dump_only=True,
        metadata=dict(
            description="The annotation's data source ID, which usually corresponds to a user (it is not the user ID, though).",
            example=19,
        ),
    )

    content = fields.Str(
        required=True,
        validate=Length(max=1024),
        metadata={
            "description": "Text content of the annotation (max 1024 characters)."
        },
    )
    start = AwareDateTimeField(
        required=True,
        format="iso",
        metadata={"description": "Start time in ISO 8601 format."},
    )
    end = AwareDateTimeField(
        required=True,
        format="iso",
        metadata={"description": "End time in ISO 8601 format."},
    )
    type = fields.Str(
        required=False,
        load_default="label",
        validate=OneOf(["alert", "holiday", "label", "feedback", "warning", "error"]),
        metadata={"description": "Type of annotation."},
    )
    belief_time = AwareDateTimeField(
        data_key="prior",
        required=False,
        allow_none=True,
        format="iso",
        metadata={
            "description": "Time when the annotation was recorded, in ISO 8601 format (default: now)."
        },
    )

    @validates_schema
    def validate_time_range(self, data, **kwargs):
        """Validate that end is after start."""
        if "start" in data and "end" in data:
            if data["end"] <= data["start"]:
                raise ValidationError("end must be after start")
