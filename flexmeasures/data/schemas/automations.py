from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from croniter.croniter import CroniterBadDateError
from marshmallow import fields, validate, validates, Schema
from pytz import all_timezones_set

from flexmeasures.data import ma, db
from flexmeasures.data.automations import validate_automation_type
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

    # The loaded names are the ones `create_automation` takes, so an endpoint can hand it the whole request.
    automation_type = fields.Str(
        data_key="type",
        load_default="forecasting",
        validate=validate_automation_type,
        metadata={
            "description": "Registered automation type: forecasting, scheduling, reporting, or a type provided by an installed plugin."
        },
    )
    name = fields.Str(required=True, validate=validate.Length(min=1, max=80))
    cronstr = CronField(required=True, data_key="cron")
    timezone = TimezoneField(
        load_default=None,
        metadata={
            "description": "IANA timezone in which the cron expression is interpreted. Defaults to the asset's own timezone, taken from its timezone attribute or one of its sensors, and to the server's FLEXMEASURES_TIMEZONE if the asset has neither.",
            "example": "Europe/Amsterdam",
        },
    )
    active = fields.Bool(load_default=True)
    parameters = fields.Dict(keys=fields.Str(), load_default=dict)
    generator_class = fields.Str(
        data_key="data-generator",
        load_default=None,
        allow_none=True,
        metadata={
            "description": "Class of the data generator that computes this automation's results, reported back as the automation's `source`."
            " A forecast automation defaults to TrainPredictPipeline, a report automation has to name its reporter (such as PandasReporter),"
            " a plugin type declares its generator, and a schedule automation's generator follows from the asset and the flex config.",
            "example": "TrainPredictPipeline",
        },
    )
    config = fields.Dict(
        keys=fields.Str(),
        load_default=dict,
        metadata={
            "description": "Configuration stored on the data generator, as opposed to the `parameters` it runs with. Used by forecast, report and plugin automation types.",
            "example": {},
        },
    )


class AutomationUpdateSchema(Schema):
    """Request schema for updating an automation's name, recurrence, timezone and/or activation status.

    The parameters cannot be updated, so the sensors an automation involves stay the ones its creator was checked against.
    """

    name = fields.Str(validate=validate.Length(min=1, max=80))
    cronstr = CronField(data_key="cron")
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
    created_at = ma.auto_field(dump_only=True, data_key="created-at")
    asset_id = ma.auto_field(data_key="asset")
    type = ma.auto_field()
    name = ma.auto_field(required=True)
    cronstr = CronField(required=True, data_key="cron")
    timezone = TimezoneField(
        metadata={
            "description": "IANA timezone in which the cron expression is interpreted.",
            "example": "Europe/Amsterdam",
        }
    )
    cursor = fields.Method(
        serialize="dump_cursor",
        dump_only=True,
        metadata={
            "description": "Time of the most recent run this automation committed to, in the automation's own timezone, as its recurrence is read there. Runs at or before it are never queued again. It advances just before queueing, so it does not indicate that queueing or the forecast itself succeeded.",
            "example": "2026-08-05T08:00:00+02:00",
        },
    )
    next_run = fields.Method(
        serialize="dump_next_run",
        data_key="next-run",
        dump_only=True,
        metadata={
            "description": "Time of the next scheduled run after the response was generated, in the automation's own timezone, so that it reads as the clock time the recurrence names. Null for an inactive automation. Pending catch-up runs are not included.",
            "example": "2026-08-05T08:00:00+02:00",
        },
    )
    active = ma.auto_field()

    @staticmethod
    def _in_automation_timezone(
        automation: Automation, moment: datetime | None
    ) -> str | None:
        """Render a moment as a clock time in the automation's own timezone.

        A recurrence is written in that timezone,
        so reading the times it produces back in UTC asks whoever reads them to undo the conversion themselves.
        """
        if moment is None:
            return None
        try:
            return moment.astimezone(ZoneInfo(automation.timezone)).isoformat()
        except (ValueError, ZoneInfoNotFoundError):
            # A stale or invalid stored timezone should not break the listing API.
            return moment.isoformat()

    def dump_next_run(self, automation: Automation) -> str | None:
        """Render the next scheduled run in the automation's own timezone."""
        return self._in_automation_timezone(automation, automation.next_run)

    def dump_cursor(self, automation: Automation) -> str | None:
        """Render the cursor in the automation's own timezone."""
        return self._in_automation_timezone(automation, automation.cursor)

    @validates("type")
    def validate_type(self, type: str, **kwargs):
        validate_automation_type(type)
