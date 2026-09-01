"""
Logic for running automations (see also the CLI command `flexmeasures jobs run-automations`).
"""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cron_descriptor import get_description, Options
from croniter import croniter
from croniter.croniter import CroniterError
import isodate
import pandas as pd
import pytz
from isodate.isoerror import ISO8601Error
from flask import current_app
from marshmallow import ValidationError
from sqlalchemy import select, update

from werkzeug.exceptions import Forbidden

from flexmeasures import Forecaster, Reporter
from flexmeasures.auth.policy import check_access
from flexmeasures.data import db
from flexmeasures.data.models.automations import (
    Automation,
    get_initial_cursor,
)
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.queries.generic_assets import (
    asset_and_ancestor_ids,
    asset_is_in_subtree,
    descendants_cte,
)
from flexmeasures.utils.time_utils import apply_offset_chain, get_timezone, server_now


@dataclass(frozen=True)
class DueAutomation:
    """An automation together with the canonical run it should handle."""

    automation: Automation
    scheduled_at: datetime
    expected_cursor: datetime | None
    expected_cronstr: str
    expected_timezone: str


# Fields naming a sensor that a scheduler records its results on, rather than reads from.
# A scheduler hands its results to `make_schedule` as (sensor, data) pairs, and these are
# the fields that decide which sensors those are: besides the power sensor of each device
# in the flex-model, its state of charge and its consumption and production sensors, plus
# the aggregates over all devices, which are defined in the flex-context.
#
# NB this list restates at set-up time what a scheduler decides at run time, so the two can drift apart.
# A scheduler that starts returning results for a sensor named by some other field would write to a sensor
# that was never checked against the creator's permissions, as this reads that sensor as an input instead.
# Extend this list whenever a flex-model or flex-context field starts naming somewhere results are recorded.
# Checking the sensors a scheduler actually returns, rather than the ones predicted here, would close the gap for good.
OUTPUT_SENSOR_FIELDS = (
    "consumption",
    "production",
    "state-of-charge",
    "state_of_charge",
    "aggregate-consumption",
    "aggregate_consumption",
    "aggregate-production",
    "aggregate_production",
)


def collect_sensors(
    value: Any,
    sensors: dict[int, Sensor] | None = None,
    only_under_output_field: bool = False,
    _under_output_field: bool = False,
) -> list[Sensor]:
    """Collect the sensors referenced anywhere in a (possibly nested) structure.

    Both deserialized sensors and the sensor references that survive deserialization
    as raw data (e.g. the flex-context and each device's flex-model, which schedulers
    deserialize themselves) are picked up.

    :param only_under_output_field: only collect the sensors that are referenced under
                                    one of the OUTPUT_SENSOR_FIELDS, at any depth.
    """
    if sensors is None:
        sensors = {}

    def collect(sensor: Sensor | None):
        if sensor is not None and (_under_output_field or not only_under_output_field):
            sensors[sensor.id] = sensor

    if isinstance(value, Sensor):
        collect(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            under_output_field = _under_output_field or key in OUTPUT_SENSOR_FIELDS
            if key == "sensor" and isinstance(item, (int, str)):
                # a sensor reference that was not deserialized, e.g. {"sensor": 12}
                if str(item).isdigit():
                    sensor = db.session.get(Sensor, int(item))
                    if sensor is not None and (
                        under_output_field or not only_under_output_field
                    ):
                        sensors[sensor.id] = sensor
            else:
                collect_sensors(
                    item, sensors, only_under_output_field, under_output_field
                )
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            collect_sensors(item, sensors, only_under_output_field, _under_output_field)
    return list(sensors.values())


def collect_schedule_output_sensors(message: dict) -> list[Sensor]:
    """The sensors that scheduling with this trigger message would record data on.

    That is the power sensor of each device in the flex-model, plus any sensor named by
    a field that defines where generated data goes (see OUTPUT_SENSOR_FIELDS), both per
    device and, for the aggregates, in the flex-context.
    """
    sensors: dict[int, Sensor] = {}
    for device in message.get("flex_model") or []:
        # each device's power sensor is what its schedule is recorded on
        collect_sensors(device.get("sensor"), sensors)
        collect_sensors(
            device.get("sensor_flex_model", device),
            sensors,
            only_under_output_field=True,
        )
    collect_sensors(message.get("flex_context"), sensors, only_under_output_field=True)
    return list(sensors.values())


def check_sensor_access(
    input_sensors: list[Sensor], output_sensors: list[Sensor]
) -> None:
    """Require access to the sensors that an automation would read from and write to.

    Reading a sensor's data requires read access to it, and recording data on a sensor
    requires the same permission as recording data through the API (create-children).
    """
    for sensors, permission, action in (
        (input_sensors, "read", "read data from"),
        (output_sensors, "create-children", "record data on"),
    ):
        for sensor in sensors:
            try:
                check_access(sensor, permission)
            except Forbidden as exc:
                setattr(
                    exc,
                    "api_message",
                    f"You cannot set up an automation that would {action} sensor"
                    f" {sensor.id}, because you cannot {action} it yourself.",
                )
                raise


def describe_cronstr(cronstr: str) -> str:
    """Describe a cron string in natural language, e.g. "At 06:00".

    Explicitly renders times in 24-hour format, as cron-descriptor otherwise
    picks a format based on the system locale.
    """
    options = Options()
    options.use_24hour_time_format = True
    try:
        return get_description(cronstr, options)
    except Exception:
        return cronstr


def floor_to_minute(dt: datetime) -> datetime:
    """Floor a timezone-aware datetime to a UTC minute."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Automation scheduling requires a timezone-aware datetime.")
    return dt.astimezone(timezone.utc).replace(second=0, microsecond=0)


def floor_to_resolution(dt: datetime, resolution: timedelta) -> datetime:
    """Floor an aware datetime to a fixed resolution without losing its DST fold."""
    delta_seconds = resolution.total_seconds()
    floored = dt.timestamp() - (dt.timestamp() % delta_seconds)
    return datetime.fromtimestamp(floored, tz=dt.tzinfo)


def _as_nominal_wall_time(dt: datetime) -> datetime:
    """Represent local wall-clock fields on a transition-free UTC timeline."""
    return datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, tzinfo=timezone.utc)


def _localize_nominal_time(
    nominal_time: datetime, timezone_info: ZoneInfo, fold: int
) -> datetime:
    """Attach a real timezone to nominal wall-clock fields using the given fold."""
    return datetime(
        nominal_time.year,
        nominal_time.month,
        nominal_time.day,
        nominal_time.hour,
        nominal_time.minute,
        tzinfo=timezone_info,
        fold=fold,
    )


def _is_valid_local_time(
    localized_time: datetime, nominal_time: datetime, timezone_info: ZoneInfo
) -> bool:
    """Return whether a localized time survives a UTC round trip unchanged."""
    round_tripped = localized_time.astimezone(timezone.utc).astimezone(timezone_info)
    return _as_nominal_wall_time(round_tripped) == nominal_time


def _valid_localizations(
    nominal_time: datetime, timezone_info: ZoneInfo
) -> list[datetime]:
    """Return the valid physical instants for a nominal wall-clock minute."""
    localizations = [
        _localize_nominal_time(nominal_time, timezone_info, fold=0),
        _localize_nominal_time(nominal_time, timezone_info, fold=1),
    ]
    valid_localizations = [
        localized_time
        for localized_time in localizations
        if _is_valid_local_time(localized_time, nominal_time, timezone_info)
    ]
    return list(
        {
            localized_time.astimezone(timezone.utc)
            for localized_time in valid_localizations
        }
    )


def _is_ambiguous_wall_time(nominal_time: datetime, timezone_info: ZoneInfo) -> bool:
    """Return whether a wall-clock minute denotes two physical instants."""
    return len(_valid_localizations(nominal_time, timezone_info)) == 2


def _canonical_run_time(nominal_time: datetime, timezone_info: ZoneInfo) -> datetime:
    """Map one wall-clock run to its canonical effective UTC instant.

    Ambiguous times use the earlier fold.
    Nonexistent times become effective at the first valid minute after the clock jump.
    """
    valid_localizations = _valid_localizations(nominal_time, timezone_info)
    if valid_localizations:
        return min(valid_localizations)

    first_valid_nominal_time = nominal_time
    for _ in range(60 * 48):
        first_valid_nominal_time += timedelta(minutes=1)
        valid_localizations = _valid_localizations(
            first_valid_nominal_time, timezone_info
        )
        if valid_localizations:
            return min(valid_localizations)
    raise ValueError(
        f"Could not find a valid local time after {nominal_time.isoformat()} in {timezone_info.key}."
    )


def _cron_evaluation_time(now: datetime, timezone_info: ZoneInfo) -> datetime:
    """Return the nominal wall time through which cron runs have happened.

    During the second fold of a repeated interval, the entire first fold has already happened.
    Evaluate through the end of that repeated wall interval, so missed runs are coalesced instead of replayed minute by minute.
    """
    localized_now = now.astimezone(timezone_info)
    nominal_now = _as_nominal_wall_time(localized_now)
    if localized_now.fold != 1 or not _is_ambiguous_wall_time(
        nominal_now, timezone_info
    ):
        return nominal_now

    nominal_after_overlap = nominal_now
    for _ in range(60 * 48):
        nominal_after_overlap += timedelta(minutes=1)
        if not _is_ambiguous_wall_time(nominal_after_overlap, timezone_info):
            return nominal_after_overlap - timedelta(minutes=1)
    raise ValueError(
        f"Could not find the end of the repeated local-time interval in {timezone_info.key}."
    )


def get_latest_scheduled_run(automation: Automation, now: datetime) -> datetime:
    """Return the latest canonical run for an automation through ``now``."""
    now = floor_to_minute(now)
    timezone_info = ZoneInfo(automation.timezone)
    evaluation_time = _cron_evaluation_time(now, timezone_info)
    if croniter.match(automation.cronstr, evaluation_time):
        nominal_run = evaluation_time
    else:
        nominal_run = croniter(automation.cronstr, evaluation_time).get_prev(datetime)
    scheduled_at = _canonical_run_time(nominal_run, timezone_info)
    if scheduled_at > now:
        raise ValueError(
            f"Cron run {nominal_run.isoformat()} in {automation.timezone} resolves after {now.isoformat()}."
        )
    return scheduled_at


def get_due_automations(now: datetime | None = None) -> list[DueAutomation]:
    """Return the newest unhandled run for each active automation."""
    if now is None:
        now = server_now()
    now = floor_to_minute(now)
    active_automations = (
        db.session.scalars(select(Automation).filter_by(active=True)).unique().all()
    )
    due_automations = []
    for automation in active_automations:
        try:
            scheduled_at = get_latest_scheduled_run(automation, now)
        except (CroniterError, ValueError, ZoneInfoNotFoundError) as exc:
            current_app.logger.error(
                "Skipping automation %s (%r), because its next run could not be calculated: %s",
                automation.id,
                automation.name,
                exc,
            )
            continue
        expected_cursor = automation.cursor
        cursor = expected_cursor
        if cursor is None:
            cursor = floor_to_minute(automation.created_at) - timedelta(minutes=1)
        if scheduled_at > cursor:
            due_automations.append(
                DueAutomation(
                    automation=automation,
                    scheduled_at=scheduled_at,
                    expected_cursor=expected_cursor,
                    expected_cronstr=automation.cronstr,
                    expected_timezone=automation.timezone,
                )
            )
    return due_automations


def claim_due_automation(due_automation: DueAutomation) -> bool:
    """Persist a run claim if its scheduling configuration is unchanged."""
    if due_automation.expected_cursor is None:
        cursor_matches = Automation.cursor.is_(None)
    else:
        cursor_matches = Automation.cursor == due_automation.expected_cursor
    result = db.session.execute(
        update(Automation)
        .where(
            Automation.id == due_automation.automation.id,
            Automation.active.is_(True),
            Automation.cronstr == due_automation.expected_cronstr,
            Automation.timezone == due_automation.expected_timezone,
            cursor_matches,
        )
        .values(cursor=due_automation.scheduled_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.session.rollback()
        return False
    db.session.commit()
    return True


class AutomationSensorsUnknown(Exception):
    """Raised when the sensors an automation involves cannot be worked out.

    Callers that decide whether something is allowed must let this propagate rather than treat it as "no sensors",
    because an automation with no known sensors would otherwise pass every check on the sensors it involves.
    """


def resolve_data_generator_sensors(
    data_generator, deserialized_parameters: dict
) -> dict[str, list[Sensor]]:
    """Ask a data generator which sensors it would read from and write to, given these parameters.

    A data generator derives this from its own config and parameters, so it also picks up a regressor that filters on sources,
    which is a sensor reference rather than a plain sensor.
    Work out the answer here rather than in each caller, so that displaying the sensors involved
    and checking access to them can never disagree about what they are.
    """
    # Work on a copy, as the data generator is cached on the data source,
    # which may be shared by several automations.
    data_generator = copy(data_generator)
    data_generator._parameters = deserialized_parameters
    return {
        "input_sensors": data_generator.input_sensors,
        "output_sensors": data_generator.output_sensors,
    }


def resolve_schedule_automation_sensors(
    parameters: dict, asset_id: int
) -> dict[str, list[Sensor]]:
    """Resolve the sensors declared by a prepared schedule trigger."""
    from flexmeasures.data.schemas.scheduling import AssetTriggerSchema
    from flexmeasures.data.services.scheduling import find_scheduler_class
    from flexmeasures.data.services.utils import get_scheduler_instance

    trigger_data = AssetTriggerSchema().load(
        prepare_schedule_trigger_message(parameters, asset_id)
    )
    start = trigger_data["start_of_schedule"]
    scheduler_params = {
        "start": start,
        "end": start + trigger_data["duration"],
        "belief_time": trigger_data.get("belief_time"),
        "resolution": trigger_data.get("resolution"),
        "flex_model": trigger_data["flex_model"],
        "flex_context": trigger_data["flex_context"],
    }
    scheduler_class = find_scheduler_class(trigger_data["asset"])
    scheduler = get_scheduler_instance(
        scheduler_class=scheduler_class,
        asset_or_sensor=trigger_data["asset"],
        scheduler_params=scheduler_params,
    )
    scheduler.collect_flex_config()

    resolved_trigger = {
        "flex_model": scheduler.flex_model,
        "flex_context": scheduler.flex_context,
    }
    output_sensors = collect_schedule_output_sensors(resolved_trigger)
    output_sensor_ids = {sensor.id for sensor in output_sensors}
    input_sensors = [
        sensor
        for sensor in collect_sensors(resolved_trigger)
        if sensor.id not in output_sensor_ids
    ]
    return {
        "input_sensors": input_sensors,
        "output_sensors": output_sensors,
    }


def resolve_automation_sensors(automation: Automation) -> dict[str, list[Sensor]]:
    """Work out which sensors an automation reads from and writes to on each run.

    Forecast and report sensors are derived from the data generator, while schedule sensors
    are derived from the same prepared trigger message used to queue the scheduling job.
    Raises `AutomationSensorsUnknown` if that cannot be done, e.g. because a forecast automation has no data generator,
    because its generator is not registered in this FlexMeasures instance,
    or because its parameters no longer load (say, after a sensor was deleted).
    Use this wherever the answer decides whether something is permitted; use `get_automation_sensors` for display.
    """
    if automation.type == "schedules":
        try:
            return resolve_schedule_automation_sensors(
                dict(automation.parameters or {}), automation.asset_id
            )
        except (NotImplementedError, ValidationError, ValueError) as exc:
            raise AutomationSensorsUnknown(
                f"Could not determine the sensors of schedule automation {automation.id}: {exc}"
            ) from exc
    if automation.generator is None:
        raise AutomationSensorsUnknown(
            f"Automation {automation.id} has no data generator, so the sensors it involves are unknown."
        )
    try:
        data_generator = automation.generator.data_generator
        parameters = dict(automation.parameters or {})
        if automation.type == "reports":
            parameters = prepare_report_parameters(
                parameters,
                automation.cronstr,
                automation_id=automation.id,
                cron_timezone=automation.timezone,
            )
        return resolve_data_generator_sensors(
            data_generator,
            data_generator._parameters_schema.load(parameters),
        )
    except (NotImplementedError, ValidationError) as e:
        raise AutomationSensorsUnknown(
            f"Could not determine the sensors of automation {automation.id}: {e}"
        ) from e


def get_automation_sensors(automation: Automation) -> dict[str, list[Sensor]]:
    """Look up which sensors an automation reads from and writes to on each run, for display purposes.

    Automations whose sensors cannot be worked out report no sensors, so that one broken automation
    does not keep a page or an API response from rendering.
    Do not use this to decide whether something is permitted, as "no sensors" then reads as "nothing to check":
    call `resolve_automation_sensors` instead and let its error propagate.
    """
    try:
        return resolve_automation_sensors(automation)
    except AutomationSensorsUnknown as e:
        current_app.logger.warning(str(e))
        return {"input_sensors": [], "output_sensors": []}


def get_automations_feeding_sensor(sensor: Sensor) -> list[Automation]:
    """Find the automations that write data to the given sensor.

    Only automations on the sensor's own asset or on one of its ancestors are
    considered, as an automation may only write to its asset's subtree
    (see `validate_automation_output_scope`). Working out the output sensors requires
    setting up each candidate's data generator, so this keeps the work proportional
    to the number of automations that could feed this sensor.

    Note that this does not filter by permission: callers showing these to a user
    should check read access on each automation (e.g. with `user_can_read`).
    """
    candidate_automations = db.session.scalars(
        select(Automation).filter(
            Automation.asset_id.in_(asset_and_ancestor_ids(sensor.generic_asset_id))
        )
    ).unique()
    return [
        automation
        for automation in candidate_automations
        if sensor.id in [output.id for output in automation.output_sensors]
    ]


def prepare_schedule_trigger_message(parameters: dict, asset_id: int) -> dict:
    """Complete stored schedule parameters into a message for the AssetTriggerSchema.

    The asset id is injected, and the (required) schedule start defaults to now,
    floored to the message's resolution (if given, otherwise to the minute),
    so recurring automations produce fresh schedules on each run.
    """
    message = dict(parameters)
    message["id"] = asset_id
    if "start" not in message:
        start = server_now()
        if message.get("resolution") is not None:
            try:
                resolution = isodate.parse_duration(message["resolution"])
            except (ISO8601Error, TypeError) as exc:
                raise ValidationError(
                    {"resolution": ["Not a valid ISO 8601 duration."]}
                ) from exc
            if not isinstance(resolution, timedelta) or resolution <= timedelta(0):
                raise ValidationError(
                    {
                        "resolution": [
                            "Schedule resolution must be a positive, fixed duration."
                        ]
                    }
                )
            start = floor_to_resolution(start, resolution)
        else:
            start = floor_to_minute(start)
        message["start"] = start.isoformat()
    return message


def validate_offset_chain(offset_chain: str):
    """Raise a ValueError on any offset that apply_offset_chain would silently skip.

    Valid offsets are Pandas offset strings, plus "DB" (day begin) and "HB" (hour begin).
    """
    from pandas.tseries.frequencies import to_offset

    for offset in str(offset_chain).split(","):
        offset = offset.strip()
        if offset.lower() in ("db", "hb"):
            continue
        try:
            to_offset(offset)
        except ValueError:
            raise ValueError(
                f"'{offset}' is not a valid Pandas offset string (nor 'DB'/'HB')."
            )


def _last_run_redis_key(automation_id: int) -> str:
    return f"automation-last-run:{automation_id}"


def record_automation_run(automation_id: int, now: datetime | None = None) -> bool:
    """Remember (in Redis) until when this automation's work is covered.

    For forecasts and schedules automations, this is the (enqueue) run time.
    For reports automations, the reporting job records the end of the report window
    instead, upon success (see run_report_job), so a failed report job does not
    create a permanent gap in the reported periods.
    """
    from redis.exceptions import WatchError

    if now is None:
        now = server_now()
    candidate = floor_to_minute(now)
    key = _last_run_redis_key(automation_id)
    connection = current_app.redis_connection
    while True:
        with connection.pipeline() as pipeline:
            try:
                pipeline.watch(key)
                value = pipeline.get(key)
                if value:
                    if isinstance(value, bytes):
                        value = value.decode()
                    try:
                        current = floor_to_minute(datetime.fromisoformat(value))
                    except ValueError:
                        current = None
                    if current is not None and current >= candidate:
                        pipeline.unwatch()
                        return False
                pipeline.multi()
                pipeline.set(key, candidate.isoformat())
                pipeline.execute()
                return True
            except WatchError:
                # Another worker updated the coverage after our read. Re-read it
                # and only advance from the new value.
                continue


def get_automation_last_run(automation_id: int) -> datetime | None:
    """Until when this automation's work is covered, if known (the record lives in Redis)."""
    from flask import current_app

    value = current_app.redis_connection.get(_last_run_redis_key(automation_id))
    if not value:
        return None
    if isinstance(value, bytes):
        value = value.decode()
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def prepare_report_parameters(
    parameters: dict,
    cronstr: str,
    now: datetime | None = None,
    automation_id: int | None = None,
    cron_timezone: str | None = None,
    scheduled_at: datetime | None = None,
) -> dict:
    """Complete stored report parameters into a message for the ReporterParametersSchema.

    The (required) start and end of the report are resolved on each run:

    - "start-offset" and "end-offset" fields hold comma-separated Pandas offsets
      (e.g. "-1D,DB" for the start of the previous day), applied to the run time
      (or to the given absolute start/end), in the timezone of the first output sensor.
    - Without offsets or absolutes, the window runs since the end of the automation's
      last (successfully) covered window, falling back to the last cron period (from
      the previous cron fire time until the run time) when none is known (e.g. on the
      first run).
    """
    message = dict(parameters)
    if scheduled_at is None:
        scheduled_at = now if now is not None else server_now()
    scheduled_at = floor_to_minute(scheduled_at)

    # Compute the run time in the timezone local to the first output sensor
    # (matching `flexmeasures add report`), falling back to the platform timezone.
    tz = get_timezone()
    outputs = message.get("output") or []
    if (
        outputs
        and isinstance(outputs[0], dict)
        and outputs[0].get("sensor") is not None
    ):
        from flexmeasures.data.models.time_series import Sensor

        try:
            output_sensor = db.session.get(Sensor, int(outputs[0]["sensor"]))
        except (TypeError, ValueError):
            output_sensor = None
        if output_sensor is not None:
            tz = pytz.timezone(output_sensor.timezone)
    now = scheduled_at.astimezone(tz)

    start_offset = message.pop("start-offset", None)
    end_offset = message.pop("end-offset", None)
    start = pd.Timestamp(message["start"]) if "start" in message else None
    end = pd.Timestamp(message["end"]) if "end" in message else None

    # Apply offsets to the given absolute datetime, or to the run time
    if start_offset is not None:
        start = apply_offset_chain(
            start if start is not None else pd.Timestamp(now), start_offset
        )
    if end_offset is not None:
        end = apply_offset_chain(
            end if end is not None else pd.Timestamp(now), end_offset
        )

    # Default to the window since the last covered window's end, falling back to
    # the last cron period (from the previous cron fire time until the run time)
    if start is None:
        last_run = (
            get_automation_last_run(automation_id)
            if automation_id is not None
            else None
        )
        if last_run is not None:
            start = last_run
        else:
            cron_tz = (
                ZoneInfo(cron_timezone)
                if cron_timezone is not None
                else ZoneInfo(str(get_timezone()))
            )
            nominal_scheduled_at = _as_nominal_wall_time(
                scheduled_at.astimezone(cron_tz)
            )
            previous_nominal = croniter(cronstr, nominal_scheduled_at).get_prev(
                datetime
            )
            start = _canonical_run_time(previous_nominal, cron_tz)
            # A skipped wall time can canonicalize to the first valid instant after
            # the gap, which may be the current run. Step back once more so
            # the first report still covers a non-empty cron period.
            if start >= scheduled_at:
                previous_nominal = croniter(cronstr, previous_nominal).get_prev(
                    datetime
                )
                start = _canonical_run_time(previous_nominal, cron_tz)
    if end is None:
        end = now

    message["start"] = pd.Timestamp(start).isoformat()
    message["end"] = pd.Timestamp(end).isoformat()
    return message


def _relevant_sensor_ids(automation: Automation, parameter_values: list) -> set[int]:
    """The asset's sensor ids, plus any (castable) sensor ids among the given parameter values."""
    sensor_ids = {sensor.id for sensor in automation.asset.sensors}
    for value in parameter_values:
        if value is not None:
            try:
                sensor_ids.add(int(value))
            except (TypeError, ValueError):
                pass
    return sensor_ids


def get_automations_involving_sensor(sensor: Sensor) -> list[Automation]:
    """Find the automations that read from or write to the given sensor.

    Unlike `get_automations_feeding_sensor`, this considers every automation, because a regressor
    may live anywhere in the tree, not just on the sensor's asset or one of its ancestors.
    That makes this proportional to the number of automations, so keep it out of hot paths;
    it is meant for rare, interactive checks, such as warning before a sensor is deleted.
    """
    involved = []
    for automation in db.session.scalars(select(Automation)).unique():
        automation_sensors = get_automation_sensors(automation)
        if sensor.id in {
            involved_sensor.id
            for key in ("input_sensors", "output_sensors")
            for involved_sensor in automation_sensors[key]
        }:
            involved.append(automation)
    return involved


def _asset_subtree_sensor_ids(asset_id: int) -> set[int]:
    """Return all sensor IDs on an asset and its descendants."""
    tree = descendants_cte(root_asset_id=asset_id, max_depth=None)
    return set(
        db.session.scalars(
            select(Sensor.id).where(Sensor.generic_asset_id.in_(select(tree.c.id)))
        ).all()
    )


def _job_cache_refs(
    automation: Automation, schedule_sensor_ids: set[int] | None = None
) -> set[tuple[int, str, str]]:
    """Return the job-cache entries in which an automation's jobs may live."""
    parameters = automation.parameters or {}
    if automation.type == "schedules":
        # Scheduling jobs are cached under the asset (multi-device wrap-up jobs)
        # and under individual device sensors (per-device jobs), which may belong
        # to child assets rather than the automation's own (site) asset.
        if schedule_sensor_ids is None:
            schedule_sensor_ids = _asset_subtree_sensor_ids(automation.asset_id)
        return {(automation.asset_id, "scheduling", "asset")} | {
            (sensor_id, "scheduling", "sensor") for sensor_id in schedule_sensor_ids
        }
    elif automation.type == "reports":
        sensor_ids = _relevant_sensor_ids(
            automation,
            [
                output.get("sensor")
                for output in parameters.get("output", []) or []
                if isinstance(output, dict)
            ],
        )
        return {(sensor_id, "reporting", "sensor") for sensor_id in sensor_ids}
    else:
        sensor_ids = _relevant_sensor_ids(
            automation,
            [parameters.get("sensor"), parameters.get("sensor-to-save")],
        )
        return {(sensor_id, "forecasting", "sensor") for sensor_id in sensor_ids}


def _count_automation_jobs(
    cache_refs: set[tuple[int, str, str]], automation_ids: set[int]
) -> dict[int, dict[str, int]]:
    """Count jobs per automation and status in one pass over the cache entries."""
    counts: dict[int, dict[str, int]] = {
        automation_id: {} for automation_id in automation_ids
    }
    seen_job_ids: set[str] = set()
    for entity_id, queue, asset_or_sensor_type in cache_refs:
        for job in current_app.job_cache.get(entity_id, queue, asset_or_sensor_type):
            if job.id in seen_job_ids:
                continue
            seen_job_ids.add(job.id)
            automation_id = job.meta.get("trigger", {}).get("automation_id")
            if automation_id in counts:
                status = str(job.get_status().value)
                counts[automation_id][status] = counts[automation_id].get(status, 0) + 1
    return counts


def get_automation_job_stats(automation: Automation) -> dict[str, int]:
    """Count the recent jobs created by this automation, per job status."""
    return _count_automation_jobs(_job_cache_refs(automation), {automation.id})[
        automation.id
    ]


def get_asset_automations_job_stats(asset) -> dict[int, dict[str, int]]:
    """Count recent jobs for all of an asset's automations in one cache pass."""
    automations = asset.automations
    if not automations:
        return {}
    schedule_sensor_ids = (
        _asset_subtree_sensor_ids(asset.id)
        if any(automation.type == "schedules" for automation in automations)
        else None
    )
    cache_refs: set[tuple[int, str, str]] = set()
    for automation in automations:
        cache_refs |= _job_cache_refs(automation, schedule_sensor_ids)
    return _count_automation_jobs(
        cache_refs, {automation.id for automation in automations}
    )


def _prepare_forecast_automation(
    asset, parameters: dict, generator_class: str | None, config: dict | None, source
) -> tuple[int, list[str]]:
    """Validate forecast automation parameters and set up the forecaster's data source."""
    from flexmeasures.data.models.time_series import Sensor
    from flexmeasures.data.schemas.forecasting.pipeline import (
        ForecasterParametersSchema,
    )
    from flexmeasures.data.services.data_sources import get_data_generator

    warnings = []
    deserialized_parameters = ForecasterParametersSchema().load(parameters)
    sensor = deserialized_parameters.get("sensor")
    if isinstance(sensor, Sensor) and sensor.generic_asset_id != asset.id:
        warnings.append(
            f"The sensor to forecast ({sensor.id}) does not belong to asset {asset.id}."
        )
    forecaster = get_data_generator(
        source=source,
        model=generator_class or "TrainPredictPipeline",
        config=config or {},
        save_config=True,
        data_generator_type=Forecaster,
    )
    if forecaster is None:
        raise ValueError(f"Could not set up forecaster '{generator_class}'.")
    generator = (
        forecaster.data_source
    )  # looks up or creates the data source storing the forecaster config
    db.session.flush()
    return generator.id, warnings


def _prepare_schedule_automation(asset, parameters: dict) -> tuple[None, list[str]]:
    """Validate schedule automation parameters (the scheduler's data source is resolved at job time)."""
    from flexmeasures.data.schemas.scheduling import AssetTriggerSchema

    warnings = []
    AssetTriggerSchema().load(prepare_schedule_trigger_message(parameters, asset.id))
    if "start" in parameters:
        warnings.append(
            "The schedule 'start' is fixed, so each run will compute the same period."
            " Omit 'start' to schedule from the run time instead."
        )
    return None, warnings


def _prepare_report_automation(
    parameters: dict,
    cronstr: str,
    generator_class: str | None,
    config: dict | None,
    source,
) -> tuple[Reporter, dict, list[str]]:
    """Validate report automation parameters without creating a data source."""
    from marshmallow import ValidationError

    from flexmeasures.data.services.data_sources import get_data_generator

    warnings = []
    if generator_class is None and source is None:
        raise ValidationError(
            "A reporter is required for report automations (e.g. PandasReporter)."
        )
    for offset_field in ("start-offset", "end-offset"):
        if offset_field in parameters:
            try:
                validate_offset_chain(parameters[offset_field])
            except ValueError as e:
                raise ValidationError(f"Invalid {offset_field}: {e}")
    reporter = get_data_generator(
        source=source,
        model=generator_class,
        config=config or {},
        save_config=True,
        data_generator_type=Reporter,
    )
    if reporter is None:
        raise ValueError(f"Could not set up reporter '{generator_class}'.")
    # Validate with the chosen reporter's own parameters schema,
    # which may extend the base ReporterParametersSchema.
    deserialized_parameters = reporter._parameters_schema.load(
        prepare_report_parameters(parameters, cronstr)
    )
    if (
        "start" in parameters or "end" in parameters
    ) and "start-offset" not in parameters:
        warnings.append(
            "The report period is (partly) fixed, so each run may compute the same period."
            " Use 'start-offset'/'end-offset' (Pandas offsets applied to the run time),"
            " or omit timing fields to report on the period since the last run instead."
        )
    return reporter, deserialized_parameters, warnings


def create_automation(
    asset,
    name: str,
    cronstr: str,
    timezone: str | None = None,
    automation_type: str = "forecasts",
    active: bool = True,
    parameters: dict | None = None,
    generator_class: str | None = None,
    config: dict | None = None,
    source=None,
    origin: str = "API",
    check_permissions: bool = False,
) -> tuple[Automation, list[str]]:
    """Create an automation (not committed yet), validating its parameters by type.

    For forecasts and reports, the data generator config is stored on a data source.
    An audit log record is added to the asset.

    :param check_permissions: whether to require that the current user may read the
                              sensors that the automation reads from, and record data
                              on the sensors it writes to. Set this for automations
                              created by a user (through the API or the UI); the CLI
                              runs without a user, and is trusted.
    :raises marshmallow.ValidationError: if the parameters are invalid.
    :raises ValueError: if the data generator cannot be set up.
    :raises werkzeug.exceptions.Forbidden: if a sensor is not accessible to the user.
    :returns: the automation and a list of warnings.
    """
    from marshmallow import ValidationError

    from flexmeasures.data.models.audit_log import AssetAuditLog

    parameters = parameters or {}
    warnings: list[str] = []
    generator_id = None
    data_generator = None
    input_sensors: list[Sensor] = []
    output_sensors: list[Sensor] = []
    if automation_type == "forecasts":
        from flexmeasures.data.services.data_sources import get_data_generator
        from flexmeasures.data.schemas.forecasting.pipeline import (
            ForecasterParametersSchema,
        )

        deserialized_parameters = ForecasterParametersSchema().load(parameters)
        sensor = deserialized_parameters.get("sensor")
        if isinstance(sensor, Sensor) and sensor.generic_asset_id != asset.id:
            warnings.append(
                f"The sensor to forecast ({sensor.id}) does not belong to asset {asset.id}."
            )
        forecaster = get_data_generator(
            source=source,
            model=generator_class or "TrainPredictPipeline",
            config=config or {},
            save_config=True,
            data_generator_type=Forecaster,
        )
        if forecaster is None:
            raise ValueError(f"Could not set up forecaster '{generator_class}'.")
        data_generator = forecaster

        # A forecast reads the history of the sensor to forecast, plus its regressors,
        # and records the forecast on the sensor to save to (the same sensor by default).
        # The forecaster works this out from the same config and parameters it will run with.
        forecast_sensors = resolve_data_generator_sensors(
            forecaster, deserialized_parameters
        )
        input_sensors = forecast_sensors["input_sensors"]
        output_sensors = forecast_sensors["output_sensors"]
    elif automation_type == "schedules":
        # A schedule is recorded on the sensors that the scheduler returns its results
        # for, and reads whatever other sensors the flex-model and flex-context refer to
        # (such as price sensors and the sensors of inflexible devices).
        schedule_sensors = resolve_schedule_automation_sensors(parameters, asset.id)
        input_sensors = schedule_sensors["input_sensors"]
        output_sensors = schedule_sensors["output_sensors"]
        if "start" in parameters:
            warnings.append(
                "The schedule 'start' is fixed, so each run will compute the same period."
                " Omit 'start' to schedule from the run time instead."
            )
    elif automation_type == "reports":
        reporter, deserialized_parameters, warnings = _prepare_report_automation(
            parameters, cronstr, generator_class, config, source
        )
        data_generator = reporter
        report_sensors = resolve_data_generator_sensors(
            reporter, deserialized_parameters
        )
        input_sensors = report_sensors["input_sensors"]
        output_sensors = report_sensors["output_sensors"]
    else:
        raise ValidationError(
            f"Automation type '{automation_type}' is not supported (supported types: {Automation.SUPPORTED_TYPES})."
        )

    if check_permissions:
        check_sensor_access(input_sensors, output_sensors)

    # Only once the sensors are known to be the user's to involve do we say anything about them,
    # so that this does not reveal where a sensor sits to someone who may not read it.
    if automation_type in ("forecasts", "reports"):
        for output_sensor in output_sensors:
            validate_automation_output_scope(asset.id, output_sensor, automation_type)

    if data_generator is not None:
        # Look up or create the data source storing the generator config only now that the automation is going ahead,
        # so that a refused request leaves nothing behind, whatever the caller does with the session afterwards.
        generator = data_generator.data_source
        db.session.flush()
        generator_id = generator.id

    automation_fields = dict(
        asset_id=asset.id,
        type=automation_type,
        name=name,
        cronstr=cronstr,
        active=active,
        generator_id=generator_id,
        parameters=parameters,
    )
    if timezone is not None:
        automation_fields["timezone"] = timezone
    automation = Automation(**automation_fields)
    db.session.add(automation)
    db.session.flush()
    AssetAuditLog.add_record(
        asset, f"Created automation '{name}' ({automation.id}) via {origin}."
    )
    return automation, warnings


def update_automation(
    automation: Automation,
    name: str | None = None,
    cronstr: str | None = None,
    timezone: str | None = None,
    active: bool | None = None,
    origin: str = "API",
) -> list[str]:
    """Update an automation's name, cron string, timezone and/or activation status (not committed yet).

    Anything that changes which runs are due, namely the recurrence, the timezone and reactivation,
    also rebases the cursor, so that runs from before the change are not caught up on.
    An audit log record is added to the asset.

    :returns: a list of (human-readable) changes; empty if nothing changed.
    """
    from flexmeasures.data.models.audit_log import AssetAuditLog

    changes = []
    rebase_schedule = False
    if name is not None and name != automation.name:
        changes.append(f"name: '{automation.name}' → '{name}'")
        automation.name = name
    if cronstr is not None and cronstr != automation.cronstr:
        changes.append(f"cron string: '{automation.cronstr}' → '{cronstr}'")
        automation.cronstr = cronstr
        rebase_schedule = True
    if timezone is not None and timezone != automation.timezone:
        changes.append(f"timezone: '{automation.timezone}' → '{timezone}'")
        automation.timezone = timezone
        rebase_schedule = True
    if active is not None and active != automation.active:
        changes.append("activated" if active else "deactivated")
        if active:
            rebase_schedule = True
        automation.active = active
    if rebase_schedule:
        automation.cursor = get_initial_cursor()
    if changes:
        AssetAuditLog.add_record(
            automation.asset,
            f"Updated automation '{automation.name}' ({automation.id}): {'; '.join(changes)}. Via {origin}.",
        )
    return changes


def delete_automation(automation: Automation, origin: str = "API"):
    """Delete an automation (not committed yet), recording it in the asset's audit log."""
    from flexmeasures.data.models.audit_log import AssetAuditLog

    AssetAuditLog.add_record(
        automation.asset,
        f"Deleted automation '{automation.name}' ({automation.id}) via {origin}.",
    )
    db.session.delete(automation)


def get_forecast_output_sensor(parameters: dict[str, Any]) -> Sensor:
    """Resolve the sensor on which a forecast automation registers beliefs."""
    sensor_reference = parameters.get("sensor-to-save")
    if sensor_reference is None:
        sensor_reference = parameters.get("sensor_to_save")
    if sensor_reference is None:
        sensor_reference = parameters.get("sensor")

    if isinstance(sensor_reference, Sensor):
        return sensor_reference
    try:
        sensor_id = int(sensor_reference)
    except (TypeError, ValueError) as exc:
        raise ValueError("Forecast automation has no valid output sensor.") from exc

    sensor = db.session.get(Sensor, sensor_id)
    if sensor is None:
        raise ValueError(
            f"Forecast automation output sensor {sensor_id} does not exist."
        )
    return sensor


def validate_automation_output_scope(
    asset_id: int, output_sensor: Sensor, automation_type: str
) -> None:
    """Require generated output on the automation asset or a descendant."""
    if not asset_is_in_subtree(asset_id, output_sensor.generic_asset_id):
        raise ValueError(
            f"{automation_type.capitalize()} automation output sensor {output_sensor.id} must belong to asset "
            f"{asset_id} or one of its descendants."
        )


def run_automation(
    automation: Automation, scheduled_at: datetime | None = None
) -> dict[str, Any] | None:
    """Queue the jobs for one run of an automation.

    :returns: a dict like {"job_id": <uuid>, "n_jobs": <int>}.
    """
    now = server_now()
    if automation.type == "forecasts":
        returns = _run_forecast_automation(automation)
    elif automation.type == "schedules":
        returns = _run_schedule_automation(automation)
    elif automation.type == "reports":
        # NB the reporting job itself records the end of the report window upon
        # success (see run_report_job), so failed jobs do not create gaps in the
        # reported periods.
        return _run_report_automation(automation, now=now, scheduled_at=scheduled_at)
    else:
        raise NotImplementedError(
            f"Automations of type '{automation.type}' cannot be run yet."
        )
    record_automation_run(automation.id, now=now)
    return returns


def _run_forecast_automation(automation: Automation) -> dict[str, Any] | None:
    if automation.generator is None:
        raise ValueError(
            f"Automation {automation.id} has no data generator to run (generator_id is not set)."
        )
    # Work on a copy, as the data generator is cached on the data source,
    # which may be shared by several automations (as in `resolve_automation_sensors`).
    forecaster = copy(automation.generator.data_generator)
    if not isinstance(forecaster, Forecaster):
        raise ValueError(
            f"Data source {automation.generator_id} of automation {automation.id} does not store a Forecaster."
        )
    output_sensor = get_forecast_output_sensor(automation.parameters or {})
    validate_automation_output_scope(
        automation.asset_id, output_sensor, automation.type
    )
    # Wipe any parameter state the copy inherited from a previous run.
    forecaster._parameters = None
    forecaster.set_job_trigger("automation", automation_id=automation.id)
    return forecaster.compute(as_job=True, parameters=dict(automation.parameters))


def _run_report_automation(
    automation: Automation,
    now: datetime | None = None,
    scheduled_at: datetime | None = None,
) -> dict[str, Any] | None:
    if automation.generator is None:
        raise ValueError(
            f"Automation {automation.id} has no data generator to run (generator_id is not set)."
        )
    reporter = automation.generator.data_generator
    if not isinstance(reporter, Reporter):
        raise ValueError(
            f"Data source {automation.generator_id} of automation {automation.id} does not store a Reporter."
        )
    parameters = prepare_report_parameters(
        dict(automation.parameters),
        automation.cronstr,
        now=now,
        automation_id=automation.id,
        cron_timezone=automation.timezone,
        scheduled_at=scheduled_at,
    )
    report_sensors = resolve_data_generator_sensors(
        reporter, reporter._parameters_schema.load(parameters)
    )
    for output_sensor in report_sensors["output_sensors"]:
        validate_automation_output_scope(
            automation.asset_id, output_sensor, automation.type
        )
    # The data generator instance is cached on the data source, which may be shared
    # by several automations, so wipe any parameter state from a previous run.
    reporter._parameters = None
    reporter.set_job_trigger("automation", automation_id=automation.id)
    return reporter.compute(as_job=True, parameters=parameters)


def _run_schedule_automation(automation: Automation) -> dict[str, Any]:
    from flexmeasures.data.schemas.scheduling import AssetTriggerSchema
    from flexmeasures.data.services.scheduling import (
        create_sequential_scheduling_job,
        create_simultaneous_scheduling_job,
    )

    message = prepare_schedule_trigger_message(
        dict(automation.parameters), automation.asset_id
    )
    trigger_data = AssetTriggerSchema().load(message)
    start = trigger_data["start_of_schedule"]
    scheduler_kwargs = dict(
        start=start,
        end=start + trigger_data["duration"],
        belief_time=trigger_data.get("belief_time"),  # server time if not set
        flex_model=trigger_data["flex_model"],
        flex_context=trigger_data["flex_context"],
    )
    if trigger_data.get("resolution") is not None:
        scheduler_kwargs["resolution"] = trigger_data["resolution"]
    if trigger_data["sequential"]:
        f = create_sequential_scheduling_job
    else:
        f = create_simultaneous_scheduling_job
    job = f(
        asset=trigger_data["asset"],
        enqueue=True,
        force_new_job_creation=trigger_data.get("force_new_job_creation", False),
        trigger={"origin": "automation", "automation_id": automation.id},
        **scheduler_kwargs,
    )
    n_jobs = len(job.args[0]) + 1 if trigger_data["sequential"] else 1
    return {"job_id": job.id, "n_jobs": n_jobs}
