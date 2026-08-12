from __future__ import annotations

from datetime import datetime, timezone

from croniter import croniter
from croniter.croniter import CroniterBadDateError
from marshmallow import fields, validate, validates, Schema, ValidationError
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
        try:
            croniter(value, datetime(2000, 1, 1, tzinfo=timezone.utc)).get_next(
                datetime
            )
        except CroniterBadDateError as exc:
            raise FMValidationError(
                f"'{value}' does not match any possible date."
            ) from exc
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


class AutomationCreationSchema(Schema):
    """Request schema for creating an automation (the asset comes from the URL path).

    The parameters are validated separately, by the schema matching the automation type.
    """

    type = fields.Str(
        load_default="forecasts",
        validate=validate.OneOf(Automation.SUPPORTED_TYPES),
    )
    name = fields.Str(required=True, validate=validate.Length(min=1, max=80))
    cronstr = CronField(required=True)
    timezone = TimezoneField(
        load_default=None,
        metadata={
            "description": "IANA timezone in which the cron expression is interpreted. Defaults to the server's FLEXMEASURES_TIMEZONE.",
            "example": "Europe/Amsterdam",
        },
    )
    active = fields.Bool(load_default=True)
    parameters = fields.Dict(keys=fields.Str(), load_default=dict)
    generator = fields.Str(
        load_default=None,
        allow_none=True,
        metadata={
            "description": "Data generator class, e.g. a forecaster (defaults to TrainPredictPipeline)"
            " or a reporter (required for type 'reports', e.g. PandasReporter)."
            " Not used for type 'schedules'."
        },
    )
    config = fields.Dict(
        keys=fields.Str(),
        load_default=dict,
        metadata={
            "description": "Data generator configuration (only used for types 'forecasts' and 'reports')."
        },
    )


class AutomationUpdateSchema(Schema):
    """Request schema for updating an automation's name, recurrence, timezone and/or activation status.

    The parameters cannot be updated, so the sensors an automation involves stay the ones its creator was checked against.
    """

    name = fields.Str(validate=validate.Length(min=1, max=80))
    cronstr = CronField()
    timezone = TimezoneField(
        metadata={
            "description": "IANA timezone in which the cron expression is interpreted.",
            "example": "Europe/Amsterdam",
        }
    )
    active = fields.Bool()


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
