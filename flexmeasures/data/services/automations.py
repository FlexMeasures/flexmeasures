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
from flask import current_app
from marshmallow import ValidationError
from sqlalchemy import select, update

from flexmeasures import Forecaster
from flexmeasures.data import db
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.queries.generic_assets import asset_is_in_subtree
from flexmeasures.utils.time_utils import server_now


@dataclass(frozen=True)
class DueAutomation:
    """An automation together with the canonical occurrence it should handle."""

    automation: Automation
    scheduled_at: datetime
    expected_cursor: datetime | None
    expected_cronstr: str
    expected_timezone: str


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


def _canonical_occurrence_time(
    nominal_time: datetime, timezone_info: ZoneInfo
) -> datetime:
    """Map one wall-clock occurrence to its canonical effective UTC instant.

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
    """Return the nominal wall time through which cron occurrences have happened.

    During the second fold of a repeated interval, the entire first fold has already happened.
    Evaluate through the end of that repeated wall interval, so missed occurrences are coalesced instead of replayed minute by minute.
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


def get_latest_scheduled_occurrence(automation: Automation, now: datetime) -> datetime:
    """Return the latest canonical occurrence for an automation through ``now``."""
    now = floor_to_minute(now)
    timezone_info = ZoneInfo(automation.timezone)
    evaluation_time = _cron_evaluation_time(now, timezone_info)
    if croniter.match(automation.cronstr, evaluation_time):
        nominal_occurrence = evaluation_time
    else:
        nominal_occurrence = croniter(automation.cronstr, evaluation_time).get_prev(
            datetime
        )
    scheduled_at = _canonical_occurrence_time(nominal_occurrence, timezone_info)
    if scheduled_at > now:
        raise ValueError(
            f"Cron occurrence {nominal_occurrence.isoformat()} in {automation.timezone} resolves after {now.isoformat()}."
        )
    return scheduled_at


def get_due_automations(now: datetime | None = None) -> list[DueAutomation]:
    """Return the newest unhandled occurrence for each active automation."""
    if now is None:
        now = server_now()
    now = floor_to_minute(now)
    active_automations = (
        db.session.scalars(select(Automation).filter_by(active=True)).unique().all()
    )
    due_automations = []
    for automation in active_automations:
        try:
            scheduled_at = get_latest_scheduled_occurrence(automation, now)
        except (CroniterError, ValueError, ZoneInfoNotFoundError) as exc:
            current_app.logger.error(
                "Skipping automation %s (%r), because its next occurrence could not be calculated: %s",
                automation.id,
                automation.name,
                exc,
            )
            continue
        expected_cursor = automation.scheduling_cursor
        scheduling_cursor = expected_cursor
        if scheduling_cursor is None:
            scheduling_cursor = floor_to_minute(automation.created_at) - timedelta(
                minutes=1
            )
        if scheduled_at > scheduling_cursor:
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
    """Persist an occurrence claim if its scheduling configuration is unchanged."""
    if due_automation.expected_cursor is None:
        cursor_matches = Automation.scheduling_cursor.is_(None)
    else:
        cursor_matches = Automation.scheduling_cursor == due_automation.expected_cursor
    result = db.session.execute(
        update(Automation)
        .where(
            Automation.id == due_automation.automation.id,
            Automation.active.is_(True),
            Automation.cronstr == due_automation.expected_cronstr,
            Automation.timezone == due_automation.expected_timezone,
            cursor_matches,
        )
        .values(scheduling_cursor=due_automation.scheduled_at)
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


def resolve_automation_sensors(automation: Automation) -> dict[str, list[Sensor]]:
    """Work out which sensors an automation reads from and writes to on each run.

    The sensors are derived from the data generator, configured with the automation's own parameters.
    Raises `AutomationSensorsUnknown` if that cannot be done, e.g. because the automation has no data generator,
    because its generator is not registered in this FlexMeasures instance,
    or because its parameters no longer load (say, after a sensor was deleted).
    Use this wherever the answer decides whether something is permitted; use `get_automation_sensors` for display.
    """
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
            Automation.asset_id.in_(_asset_and_ancestor_ids(sensor.generic_asset_id))
        )
    ).unique()
    return [
        automation
        for automation in candidate_automations
        if sensor.id in [output.id for output in automation.output_sensors]
    ]


def _asset_and_ancestor_ids(asset_id: int | None) -> list[int]:
    """List the given asset and all of its ancestors, nearest first."""
    from flexmeasures.data.models.generic_assets import GenericAsset

    asset_ids: list[int] = []
    while asset_id is not None and asset_id not in asset_ids:
        asset_ids.append(asset_id)
        asset = db.session.get(GenericAsset, asset_id)
        if asset is None:
            break
        asset_id = asset.parent_asset_id
    return asset_ids


def get_automation_job_stats(automation: Automation) -> dict[str, int]:
    """Count the jobs created by this automation, per job status.

    Note that jobs in Redis have a limited TTL, so this only counts fairly recent jobs.
    """
    # Jobs are cached under the forecast target sensor(s), which may belong
    # to a different asset than the automation's own asset.
    sensor_ids = {sensor.id for sensor in automation.asset.sensors}
    for key in ("sensor", "sensor-to-save"):
        value = (automation.parameters or {}).get(key)
        if value is not None:
            try:
                sensor_ids.add(int(value))
            except (TypeError, ValueError):
                pass

    counts: dict[str, int] = {}
    seen_job_ids: set[str] = set()
    for sensor_id in sensor_ids:
        for job in current_app.job_cache.get(sensor_id, "forecasting", "sensor"):
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

    :returns: the data generator's return value, e.g. {"job_id": <uuid>, "n_jobs": <int>}
              for forecasting jobs.
    """
    if automation.type != "forecasts":
        raise NotImplementedError(
            f"Automations of type '{automation.type}' cannot be run yet."
        )
    if automation.generator is None:
        raise ValueError(
            f"Automation {automation.id} has no data generator to run (generator_id is not set)."
        )
    forecaster = automation.generator.data_generator
    if not isinstance(forecaster, Forecaster):
        raise ValueError(
            f"Data source {automation.generator_id} of automation {automation.id} does not store a Forecaster."
        )
    output_sensor = get_forecast_output_sensor(automation.parameters or {})
    validate_forecast_output_scope(automation.asset_id, output_sensor)
    # The data generator instance is cached on the data source, which may be shared
    # by several automations, so wipe any parameter state from a previous run.
    forecaster._parameters = None
    forecaster.set_job_trigger("automation", automation_id=automation.id)
    return forecaster.compute(as_job=True, parameters=dict(automation.parameters))
