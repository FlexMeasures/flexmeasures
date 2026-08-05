from __future__ import annotations

from croniter import croniter
from marshmallow import fields, validates, ValidationError
from pytz import all_timezones_set

from flexmeasures.data import ma, db
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.schemas.utils import (
    FMValidationError,
    MarshmallowClickMixin,
    with_appcontext_if_needed,
)


class CronField(MarshmallowClickMixin, fields.Str):
    """Field that validates a cron string (e.g. "0 6 * * *")."""

    def _deserialize(self, value, attr, obj, **kwargs) -> str:
        value = super()._deserialize(value, attr, obj, **kwargs)
        if len(value.split()) != 5:
            raise FMValidationError(
                "Automation cron expressions must contain exactly five fields "
                "(minute, hour, day of month, month, and day of week)."
            )
        if not croniter.is_valid(value):
            raise FMValidationError(f"'{value}' is not a valid cron string.")
        return value


class TimezoneField(MarshmallowClickMixin, fields.Str):
    """Field that validates an exact IANA timezone name."""

    def _deserialize(self, value, attr, obj, **kwargs) -> str:
        value = super()._deserialize(value, attr, obj, **kwargs)
        if value not in all_timezones_set:
            raise FMValidationError(f"Timezone '{value}' does not exist.")
        return value


class AutomationIdField(MarshmallowClickMixin, fields.Int):
    """Field that deserializes to an Automation and serializes back to an integer."""

    @with_appcontext_if_needed()
    def _deserialize(self, value, attr, obj, **kwargs) -> Automation:
        """Turn an automation id into an Automation."""
        value = super()._deserialize(value, attr, obj, **kwargs)
        automation = db.session.get(Automation, value)
        if automation is None:
            raise FMValidationError(f"No automation found with id {value}.")
        return automation

    def _serialize(self, automation, attr, data, **kwargs):
        """Turn an Automation into an automation id."""
        return automation.id


class AutomationSchema(ma.SQLAlchemySchema):
    """Automation schema, with validations."""

    class Meta:
        model = Automation

    id = ma.auto_field(dump_only=True)
    created_at = ma.auto_field(dump_only=True)
    asset_id = ma.auto_field()
    type = ma.auto_field()
    name = ma.auto_field(required=True)
    cronstr = CronField(required=True)
    timezone = TimezoneField(
        metadata={
            "description": "IANA timezone in which the cron expression is interpreted.",
            "example": "Europe/Amsterdam",
        }
    )
    scheduling_cursor = ma.auto_field(
        dump_only=True,
        metadata={
            "description": "UTC scheduling watermark. Occurrences at or before this timestamp are ineligible for another automatic queueing attempt; it is not a successful-run timestamp.",
            "example": "2026-08-05T06:00:00+00:00",
        },
    )
    active = ma.auto_field()

    @validates("type")
    def validate_type(self, type: str, **kwargs):
        if type not in Automation.SUPPORTED_TYPES:
            raise ValidationError(
                f"Automation type '{type}' is not supported (supported types: {Automation.SUPPORTED_TYPES})."
            )
