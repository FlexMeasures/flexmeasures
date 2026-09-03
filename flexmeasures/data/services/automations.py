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
from isodate.isoerror import ISO8601Error
from flask import current_app
from marshmallow import ValidationError
from sqlalchemy import select, update

from flexmeasures import Forecaster
from flexmeasures.data import db
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.queries.generic_assets import (
    asset_and_ancestor_ids,
    asset_is_in_subtree,
)
from flexmeasures.utils.time_utils import server_now


@dataclass(frozen=True)
class DueAutomation:
    """An automation together with the canonical run it should handle."""

    automation: Automation
    scheduled_at: datetime
    expected_cursor: datetime | None
    expected_cronstr: str
    expected_timezone: str


# Fields naming sensors on which a scheduler records generated schedules.
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
    """Collect sensor objects and references from a nested scheduling structure."""
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
    """Collect sensors on which the prepared schedule trigger records results."""
    sensors: dict[int, Sensor] = {}
    for device in message.get("flex_model") or []:
        collect_sensors(device.get("sensor"), sensors)
        collect_sensors(
            device.get("sensor_flex_model", device),
            sensors,
            only_under_output_field=True,
        )
    collect_sensors(message.get("flex_context"), sensors, only_under_output_field=True)
    return list(sensors.values())


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


def resolve_schedule_automation_sensors(
    parameters: dict, asset_id: int
) -> dict[str, list[Sensor]]:
    """Resolve the sensors declared by a prepared schedule trigger."""
    from flexmeasures.data.schemas.scheduling import AssetTriggerSchema
    from flexmeasures.data.services.scheduling import find_scheduler_class
    from flexmeasures.data.services.utils import get_scheduler_instance

    try:
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
    except (NotImplementedError, ValidationError, ValueError) as exc:
        raise AutomationSensorsUnknown(
            f"Could not determine the sensors of schedule automation on asset {asset_id}: {exc}"
        ) from exc

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

    Forecast sensors are derived from the data generator, while schedule sensors are
    derived from the same prepared trigger message used to queue the scheduling job.
    Raises `AutomationSensorsUnknown` if that cannot be done, e.g. because a forecast automation has no data generator,
    because its generator is not registered in this FlexMeasures instance,
    or because its parameters no longer load (say, after a sensor was deleted).
    Use this wherever the answer decides whether something is permitted; use `get_automation_sensors` for display.
    """
    if automation.type == "scheduling":
        return resolve_schedule_automation_sensors(
            dict(automation.parameters or {}), automation.asset_id
        )
    if automation.generator is None:
        raise AutomationSensorsUnknown(
            f"Automation {automation.id} has no data generator, so the sensors it involves are unknown."
        )
    try:
        # Work on a copy, as the data generator is cached on the data source,
        # which may be shared by several automations.
        data_generator = copy(automation.generator.data_generator)
        data_generator._parameters = data_generator._parameters_schema.load(
            dict(automation.parameters or {})
        )
        return {
            "input_sensors": data_generator.input_sensors,
            "output_sensors": data_generator.output_sensors,
        }
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
    (see `validate_forecast_output_scope`). Working out the output sensors requires
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


def resolve_schedule_generator(asset_id: int, parameters: dict) -> DataSource:
    """The data source describing the scheduler a schedule automation runs, and the flex config it runs with.

    The scheduler class follows from the asset, and the config is the trigger message merged with what the asset tree stores,
    so both can change without the automation changing.
    That is why this is resolved afresh on every run, rather than only when the automation is created.
    """
    from flexmeasures.data.schemas.scheduling import AssetTriggerSchema
    from flexmeasures.data.services.scheduling import (
        find_scheduler_class,
        get_scheduler_instance,
    )

    message = prepare_schedule_trigger_message(dict(parameters or {}), asset_id)
    trigger_data = AssetTriggerSchema().load(message)
    asset = trigger_data["asset"]
    scheduler = get_scheduler_instance(
        scheduler_class=find_scheduler_class(asset),
        asset_or_sensor=asset,
        scheduler_params=dict(
            start=trigger_data["start_of_schedule"],
            end=trigger_data["start_of_schedule"] + trigger_data["duration"],
            # The flex config goes in as the message spells it, which is the form the data source records.
            flex_model=message.get("flex-model"),
            flex_context=message.get("flex-context"),
            return_multiple=True,
        ),
    )
    return scheduler.data_source


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


def get_automation_job_stats(automation: Automation) -> dict[str, int]:
    """Count the jobs created by this automation, per job status.

    Note that jobs in Redis have a limited TTL, so this only counts fairly recent jobs.
    """
    # Determine the job cache entries to scan.
    if automation.type == "scheduling":
        # Scheduling jobs are cached under the asset (multi-device wrap-up jobs)
        # and under individual sensors (per-device jobs).
        assets = [automation.asset, *automation.asset.offspring]
        cache_refs = [(automation.asset_id, "scheduling", "asset")] + [
            (sensor.id, "scheduling", "sensor")
            for asset in assets
            for sensor in asset.sensors
        ]
    else:
        # Forecasting jobs are cached under the forecast target sensor(s),
        # which may belong to a different asset than the automation's own asset.
        sensor_ids = {sensor.id for sensor in automation.asset.sensors}
        for key in ("sensor", "sensor-to-save"):
            value = (automation.parameters or {}).get(key)
            if value is not None:
                try:
                    sensor_ids.add(int(value))
                except (TypeError, ValueError):
                    pass
        cache_refs = [(sensor_id, "forecasting", "sensor") for sensor_id in sensor_ids]

    counts: dict[str, int] = {}
    seen_job_ids: set[str] = set()
    for entity_id, queue, asset_or_sensor_type in cache_refs:
        for job in current_app.job_cache.get(entity_id, queue, asset_or_sensor_type):
            if job.id in seen_job_ids:
                continue
            seen_job_ids.add(job.id)
            if job.meta.get("trigger", {}).get("automation_id") == automation.id:
                status = str(job.get_status().value)
                counts[status] = counts.get(status, 0) + 1
    return counts


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


def validate_forecast_output_scope(asset_id: int, output_sensor: Sensor) -> None:
    """Require forecast output on the automation asset or a descendant."""
    if not asset_is_in_subtree(asset_id, output_sensor.generic_asset_id):
        raise ValueError(
            f"Forecast automation output sensor {output_sensor.id} must belong to asset "
            f"{asset_id} or one of its descendants."
        )


def run_automation(automation: Automation) -> dict[str, Any] | None:
    """Queue the jobs for one run of an automation.

    :returns: a dict like {"job_id": <uuid>, "n_jobs": <int>}.
    """
    if automation.type == "forecasting":
        return _run_forecast_automation(automation)
    elif automation.type == "scheduling":
        return _run_schedule_automation(automation)
    raise NotImplementedError(
        f"Automations of type '{automation.type}' cannot be run yet."
    )


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
    validate_forecast_output_scope(automation.asset_id, output_sensor)
    # Wipe any parameter state the copy inherited from a previous run.
    forecaster._parameters = None
    forecaster.set_job_trigger("automation", automation_id=automation.id)
    return forecaster.compute(as_job=True, parameters=dict(automation.parameters))


def _run_schedule_automation(automation: Automation) -> dict[str, Any]:
    from flexmeasures.data.schemas.scheduling import AssetTriggerSchema
    from flexmeasures.data.services.scheduling import (
        create_sequential_scheduling_job,
        create_simultaneous_scheduling_job,
    )

    # The scheduler and the flex config it merges in can both change between runs,
    # so record which data source this run actually computes under.
    generator = resolve_schedule_generator(automation.asset_id, automation.parameters)
    if automation.generator_id != generator.id:
        automation.generator_id = generator.id
        db.session.commit()

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
