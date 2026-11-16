from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from croniter.croniter import CroniterBadDateError
from marshmallow import (
    fields,
    validate,
    validates,
    validates_schema,
    Schema,
    ValidationError,
)

from flexmeasures.data import db, ma
from flexmeasures.data.automations import validate_automation_type
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.schemas.sources import DataSourceIdField
from flexmeasures.data.schemas.times import TimezoneField
from flexmeasures.data.schemas.utils import (
    get_by_id,
    FMValidationError,
    MarshmallowClickMixin,
    with_appcontext_if_needed,
)


class CronField(MarshmallowClickMixin, fields.Str):
    """Field that validates a cron string (e.g. ``"0 6 * * *"``)."""

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


class AutomationIdField(MarshmallowClickMixin, fields.Int):
    """Field that deserializes to an Automation and serializes back to an integer."""

    @with_appcontext_if_needed()
    def _deserialize(self, value, attr, obj, **kwargs) -> Automation:
        """Turn an automation id into an Automation."""
        value = super()._deserialize(value, attr, obj, **kwargs)
        automation = get_by_id(Automation, value)
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
    source = DataSourceIdField(
        required=False,
        # Leaving the source out and sending a null one both mean that the automation sets up its own data generator,
        # which is what a client sends when it fills in the rest of the form and leaves the source field empty.
        allow_none=True,
        metadata={
            "description": "ID of an existing data source to reuse, instead of naming a `data-generator` and its `config`.",
            "example": 6,
        },
    )

    @validates_schema
    def validate_generator_is_named_once(self, data: dict, **kwargs):
        """A data source already determines the data generator and its config, so the two ways of naming one are exclusive."""
        if data.get("source") is None:
            return
        named_alongside = [
            data_key
            for data_key, value in (
                ("data-generator", data.get("generator_class")),
                ("config", data.get("config")),
            )
            if value
        ]
        if named_alongside:
            raise ValidationError(
                f"{' and '.join(named_alongside)} cannot be combined with source:"
                " a data source already stores the data generator and the configuration it runs under.",
                field_name="source",
            )
        if data.get("automation_type") == "scheduling":
            raise ValidationError(
                "A schedule automation cannot name a source:"
                " its data source follows from the asset and the flex config, and is resolved afresh on every run.",
                field_name="source",
            )


class AutomationUpdateSchema(Schema):
    """Request schema for updating an automation.

    The parameters, data generator, config and data source are validated separately, as on creation, against the automation's type.
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
    parameters = fields.Dict(
        keys=fields.Str(),
        metadata={
            "description": "New parameters, replacing the current ones as a whole.",
        },
    )
    generator_class = fields.Str(
        data_key="data-generator",
        metadata={
            "description": "Class of a new data generator. Leaving out the config keeps the current one.",
            "example": "TrainPredictPipeline",
        },
    )
    config = fields.Dict(
        keys=fields.Str(),
        metadata={
            "description": "New configuration for the data generator, replacing the current one as a whole."
            " The automation moves to the data source storing it, and the old data source is left as it is.",
            "example": {},
        },
    )
    source = DataSourceIdField(
        metadata={
            "description": "ID of an existing data source to move the automation to, instead of naming a `data-generator` and its `config`.",
            "example": 6,
        },
    )
    run_as_me = fields.Bool(
        data_key="run-as-me",
        metadata={
            "description": "Have the automation run as you from now on, so that every run checks your access,"
            " rather than that of the user it runs as now (its creator, at first)."
            " Without it, a change of what the automation computes has to pass the access checks of both you and that user."
            " Use this to take over an automation whose runs are refused, for instance because that user's account was deactivated, or they no longer have access to one of its sensors.",
            "example": True,
        },
    )

    @validates_schema
    def validate_generator_is_named_once(self, data: dict, **kwargs):
        """A data source already determines the data generator and its config, so the two ways of naming one are exclusive."""
        if data.get("source") is None:
            return
        named_alongside = [
            data_key
            for data_key, field_name in (
                ("data-generator", "generator_class"),
                ("config", "config"),
            )
            if field_name in data
        ]
        if named_alongside:
            raise ValidationError(
                f"{' and '.join(named_alongside)} cannot be combined with source:"
                " a data source already stores the data generator and the configuration it runs under.",
                field_name="source",
            )


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
    revision = ma.auto_field(
        dump_only=True,
        metadata={
            "description": "Counts the edits that changed when the automation runs or what it computes, and its reactivations; it keeps the durable runs from before and after such a change apart.",
            "example": 2,
        },
    )
    active = ma.auto_field()
    runs_as = fields.Method(
        serialize="dump_runs_as",
        data_key="runs-as",
        dump_only=True,
        metadata={
            "description": "The user whose access every run of the automation checks: its creator, unless someone took it over with `run-as-me`."
            " Null for an automation set up through the CLI, which is trusted, so that its runs check nobody's access."
            " The name is null if that user no longer exists.",
            "example": {"id": 2, "name": "toy-user"},
        },
    )

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

    def dump_runs_as(self, automation: Automation) -> dict | None:
        """Name the user whom the automation runs as, as nothing else shows it."""
        from flexmeasures.data.models.user import User

        if automation.execution_user_id is None:
            return None
        user = db.session.get(User, automation.execution_user_id)
        return {
            "id": automation.execution_user_id,
            "name": user.username if user is not None else None,
        }

    @validates("type")
    def validate_type(self, type: str, **kwargs):
        validate_automation_type(type)
