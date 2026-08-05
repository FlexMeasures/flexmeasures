"""
Logic for running automations (see also the CLI command `flexmeasures jobs run-automations`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from cron_descriptor import get_description, Options
from croniter import croniter
from sqlalchemy import or_, select, update

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
        scheduled_at = get_latest_scheduled_occurrence(automation, now)
        scheduling_cursor = automation.scheduling_cursor
        if scheduling_cursor is None:
            scheduling_cursor = floor_to_minute(automation.created_at) - timedelta(
                minutes=1
            )
        if scheduled_at > scheduling_cursor:
            due_automations.append(
                DueAutomation(automation=automation, scheduled_at=scheduled_at)
            )
    return due_automations


def claim_due_automation(due_automation: DueAutomation) -> bool:
    """Persist an occurrence claim before its non-transactional queueing attempt."""
    result = db.session.execute(
        update(Automation)
        .where(
            Automation.id == due_automation.automation.id,
            or_(
                Automation.scheduling_cursor.is_(None),
                Automation.scheduling_cursor < due_automation.scheduled_at,
            ),
        )
        .values(scheduling_cursor=due_automation.scheduled_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.session.rollback()
        return False
    db.session.commit()
    return True


def get_automation_job_stats(automation: Automation) -> dict[str, int]:
    """Count the jobs created by this automation, per job status.

    Note that jobs in Redis have a limited TTL, so this only counts fairly recent jobs.
    """
    from flask import current_app

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
