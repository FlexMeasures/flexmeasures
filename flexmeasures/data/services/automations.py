"""
Logic for running automations (see also the CLI command `flexmeasures jobs run-automations`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cron_descriptor import get_description, Options
from croniter import croniter
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


def get_automation_job_stats(automation: Automation) -> dict[str, int]:
    """Count the jobs created by this automation, per job status.

    Note that jobs in Redis have a limited TTL, so this only counts fairly recent jobs.
    """
    from flask import current_app

    counts: dict[str, int] = {}
    for sensor in automation.asset.sensors:
        for job in current_app.job_cache.get(sensor.id, "forecasting", "sensor"):
            if job.meta.get("trigger", {}).get("automation_id") == automation.id:
                status = str(job.get_status().value)
                counts[status] = counts.get(status, 0) + 1
    return counts


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
    forecaster.set_job_trigger("automation", automation_id=automation.id)
    return forecaster.compute(as_job=True, parameters=dict(automation.parameters))
