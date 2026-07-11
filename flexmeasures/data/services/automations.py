"""
Logic for running automations (see also the CLI command `flexmeasures jobs run-automations`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cron_descriptor import get_description, Options
from croniter import croniter
import isodate
import pandas as pd
from sqlalchemy import select

from flexmeasures import Forecaster
from flexmeasures.data import db
from flexmeasures.data.models.automations import Automation
from flexmeasures.utils.time_utils import get_timezone, server_now


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
    """Floor a datetime to the minute, in the FLEXMEASURES_TIMEZONE."""
    return dt.astimezone(get_timezone()).replace(second=0, microsecond=0)


def get_due_automations(now: datetime | None = None) -> list[Automation]:
    """Return active automations whose cron string matches the given (or current) minute.

    Cron strings are interpreted in the FLEXMEASURES_TIMEZONE.
    """
    if now is None:
        now = server_now()
    now = floor_to_minute(now)
    active_automations = (
        db.session.scalars(select(Automation).filter_by(active=True)).unique().all()
    )
    return [
        automation
        for automation in active_automations
        if croniter.match(automation.cronstr, now)
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
        start = floor_to_minute(server_now())
        if message.get("resolution") is not None:
            try:
                resolution = isodate.parse_duration(message["resolution"])
                start = (
                    pd.Timestamp(start).floor(pd.Timedelta(resolution)).to_pydatetime()
                )
            except Exception:
                pass  # leave start floored to the minute
        message["start"] = start.isoformat()
    return message


def get_automation_job_stats(automation: Automation) -> dict[str, int]:
    """Count the jobs created by this automation, per job status.

    Note that jobs in Redis have a limited TTL, so this only counts fairly recent jobs.
    """
    from flask import current_app

    # Determine the job cache entries to scan.
    if automation.type == "schedules":
        # Scheduling jobs are cached under the asset (multi-device wrap-up jobs)
        # and under individual sensors (per-device jobs).
        cache_refs = [(automation.asset_id, "scheduling", "asset")] + [
            (sensor.id, "scheduling", "sensor") for sensor in automation.asset.sensors
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


def run_automation(automation: Automation) -> dict[str, Any] | None:
    """Queue the jobs for one run of an automation.

    :returns: a dict like {"job_id": <uuid>, "n_jobs": <int>}.
    """
    if automation.type == "forecasts":
        return _run_forecast_automation(automation)
    elif automation.type == "schedules":
        return _run_schedule_automation(automation)
    raise NotImplementedError(
        f"Automations of type '{automation.type}' cannot be run yet."
    )


def _run_forecast_automation(automation: Automation) -> dict[str, Any] | None:
    if automation.generator is None:
        raise ValueError(
            f"Automation {automation.id} has no data generator to run (generator_id is not set)."
        )
    forecaster = automation.generator.data_generator
    if not isinstance(forecaster, Forecaster):
        raise ValueError(
            f"Data source {automation.generator_id} of automation {automation.id} does not store a Forecaster."
        )
    # The data generator instance is cached on the data source, which may be shared
    # by several automations, so wipe any parameter state from a previous run.
    forecaster._parameters = None
    forecaster.set_job_trigger("automation", automation_id=automation.id)
    return forecaster.compute(as_job=True, parameters=dict(automation.parameters))


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
        resolution=trigger_data.get("resolution"),
        flex_model=trigger_data["flex_model"],
        flex_context=trigger_data["flex_context"],
    )
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
    return {"job_id": job.id, "n_jobs": 1}
