"""
Logic for running automations (see also the CLI command `flexmeasures jobs run-automations`).
"""

from __future__ import annotations

from copy import copy
from datetime import datetime
from typing import Any

from cron_descriptor import get_description, Options
from croniter import croniter
from flask import current_app
from sqlalchemy import select

from flexmeasures import Forecaster
from flexmeasures.data import db
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.queries.generic_assets import asset_is_in_subtree
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


def get_automation_sensors(automation: Automation) -> dict[str, list[Sensor]]:
    """Look up which sensors an automation reads from and writes to on each run.

    The sensors are derived from the data generator, configured with the automation's
    own parameters. Automations whose data generator or parameters cannot be loaded
    (e.g. because a sensor was deleted) report no sensors.
    """
    no_sensors: dict[str, list[Sensor]] = {"input_sensors": [], "output_sensors": []}
    if automation.generator is None:
        return no_sensors
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
    except Exception as e:
        current_app.logger.warning(
            f"Could not determine the sensors of automation {automation.id}: {e}"
        )
        return no_sensors


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
