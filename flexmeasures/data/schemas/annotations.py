from __future__ import annotations

from flask_security import current_user
from marshmallow import Schema, fields, post_load, validates_schema, ValidationError
from marshmallow.validate import OneOf, Length

from flexmeasures.data.models.annotations import Annotation
from flexmeasures.data.schemas.times import AwareDateTimeField
from flexmeasures.data.services.data_sources import get_or_create_source


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
            "description": "Text content of the annotation (max 1024 characters).",
            "examples": [
                "Server maintenance",
                "Installation upgrade",
                "Operation Main Strike",
            ],
        },
    )
    start = AwareDateTimeField(
        required=True,
        format="iso",
        metadata={
            "description": "Start time in ISO 8601 format.",
            "example": "2026-02-11T17:52:03+01:00",
        },
    )
    end = AwareDateTimeField(
        required=True,
        format="iso",
        metadata={
            "description": "End time in ISO 8601 format.",
            "example": "2026-02-11T19:00:00+01:00",
        },
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
            "description": "Time when the annotation was recorded, in ISO 8601 format (default: now).",
            "example": "2026-02-01T17:43:56+01:00",
        },
    )

    @validates_schema
    def validate_time_range(self, data, **kwargs):
        """Validate that end is after start."""
        if "start" in data and "end" in data:
            if data["end"] <= data["start"]:
                raise ValidationError("end must be after start")

    @post_load
    def to_annotation(self, data: dict, *args, **kwargs) -> Annotation:
        """Load annotation data into a user-sourced annotation object."""
        source = get_or_create_source(current_user)
        annotation = Annotation(
            content=data["content"],
            start=data["start"],
            end=data["end"],
            type=data.get("type", "label"),
            belief_time=data.get("belief_time"),
            source=source,
        )
        return annotation
