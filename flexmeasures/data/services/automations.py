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
import pytz
from sqlalchemy import select

from flexmeasures import Forecaster, Reporter
from flexmeasures.data import db
from flexmeasures.data.models.automations import Automation
from flexmeasures.utils.time_utils import (
    apply_offset_chain,
    get_timezone,
    server_now,
)


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


def prepare_report_parameters(
    parameters: dict, cronstr: str, now: datetime | None = None
) -> dict:
    """Complete stored report parameters into a message for the ReporterParametersSchema.

    The (required) start and end of the report are resolved on each run:

    - "start-offset" and "end-offset" fields hold comma-separated Pandas offsets
      (e.g. "-1D,DB" for the start of the previous day), applied to the run time
      (or to the given absolute start/end), in the timezone of the first output sensor.
    - Without offsets or absolutes, the window defaults to the last cron period:
      from the previous cron fire time until the run time.
    """
    message = dict(parameters)
    if now is None:
        now = server_now()
    now = floor_to_minute(now)

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
    now = now.astimezone(tz)

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

    # Default to the last cron period: from the previous cron fire time until the run time
    if start is None:
        start = croniter(cronstr, now).get_prev(datetime)
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


def get_automation_job_stats(automation: Automation) -> dict[str, int]:
    """Count the jobs created by this automation, per job status.

    Note that jobs in Redis have a limited TTL, so this only counts fairly recent jobs.
    """
    from flask import current_app

    # Determine the job cache entries to scan. Forecasting and reporting jobs
    # are cached under their target/output sensor(s), which may belong to a
    # different asset than the automation's own asset.
    parameters = automation.parameters or {}
    if automation.type == "schedules":
        # Scheduling jobs are cached under the asset (multi-device wrap-up jobs)
        # and under individual sensors (per-device jobs).
        cache_refs = [(automation.asset_id, "scheduling", "asset")] + [
            (sensor.id, "scheduling", "sensor") for sensor in automation.asset.sensors
        ]
    elif automation.type == "reports":
        sensor_ids = _relevant_sensor_ids(
            automation,
            [
                output.get("sensor")
                for output in parameters.get("output", []) or []
                if isinstance(output, dict)
            ],
        )
        cache_refs = [(sensor_id, "reporting", "sensor") for sensor_id in sensor_ids]
    else:
        sensor_ids = _relevant_sensor_ids(
            automation,
            [parameters.get("sensor"), parameters.get("sensor-to-save")],
        )
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


def create_automation(
    asset,
    name: str,
    cronstr: str,
    automation_type: str = "forecasts",
    active: bool = True,
    parameters: dict | None = None,
    generator_class: str | None = None,
    config: dict | None = None,
    source=None,
    origin: str = "API",
) -> tuple[Automation, list[str]]:
    """Create an automation (not committed yet), validating its parameters by type.

    For forecasts and reports, the data generator config is stored on a data source.
    An audit log record is added to the asset.

    :raises marshmallow.ValidationError: if the parameters are invalid.
    :raises ValueError: if the data generator cannot be set up.
    :returns: the automation and a list of warnings.
    """
    from marshmallow import ValidationError

    from flexmeasures.data.models.audit_log import AssetAuditLog
    from flexmeasures.data.models.time_series import Sensor
    from flexmeasures.data.services.data_sources import get_data_generator

    parameters = parameters or {}
    warnings: list[str] = []
    generator_id = None
    if automation_type == "forecasts":
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
        generator = (
            forecaster.data_source
        )  # looks up or creates the data source storing the forecaster config
        db.session.flush()
        generator_id = generator.id
    elif automation_type == "schedules":
        from flexmeasures.data.schemas.scheduling import AssetTriggerSchema

        AssetTriggerSchema().load(
            prepare_schedule_trigger_message(parameters, asset.id)
        )
        if "start" in parameters:
            warnings.append(
                "The schedule 'start' is fixed, so each run will compute the same period."
                " Omit 'start' to schedule from the run time instead."
            )
    elif automation_type == "reports":
        from flexmeasures.data.schemas.reporting import ReporterParametersSchema

        if generator_class is None and source is None:
            raise ValidationError(
                "A reporter is required for report automations (e.g. PandasReporter)."
            )
        try:
            prepared_parameters = prepare_report_parameters(parameters, cronstr)
        except ValueError as e:
            raise ValidationError(f"Invalid time offsets: {e}")
        ReporterParametersSchema().load(prepared_parameters)
        if (
            "start" in parameters or "end" in parameters
        ) and "start-offset" not in parameters:
            warnings.append(
                "The report period is (partly) fixed, so each run may compute the same period."
                " Use 'start-offset'/'end-offset' (Pandas offsets applied to the run time),"
                " or omit timing fields to report on the last cron period instead."
            )
        reporter = get_data_generator(
            source=source,
            model=generator_class,
            config=config or {},
            save_config=True,
            data_generator_type=Reporter,
        )
        if reporter is None:
            raise ValueError(f"Could not set up reporter '{generator_class}'.")
        generator = (
            reporter.data_source
        )  # looks up or creates the data source storing the reporter config
        db.session.flush()
        generator_id = generator.id
    else:
        raise ValidationError(
            f"Automation type '{automation_type}' is not supported (supported types: {Automation.SUPPORTED_TYPES})."
        )

    automation = Automation(
        asset_id=asset.id,
        type=automation_type,
        name=name,
        cronstr=cronstr,
        active=active,
        generator_id=generator_id,
        parameters=parameters,
    )
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
    active: bool | None = None,
    origin: str = "API",
) -> list[str]:
    """Update an automation's name, cron string and/or activation status (not committed yet).

    An audit log record is added to the asset.

    :returns: a list of (human-readable) changes; empty if nothing changed.
    """
    from flexmeasures.data.models.audit_log import AssetAuditLog

    changes = []
    if name is not None and name != automation.name:
        changes.append(f"name: '{automation.name}' → '{name}'")
        automation.name = name
    if cronstr is not None and cronstr != automation.cronstr:
        changes.append(f"cron string: '{automation.cronstr}' → '{cronstr}'")
        automation.cronstr = cronstr
    if active is not None and active != automation.active:
        changes.append("activated" if active else "deactivated")
        automation.active = active
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


def run_automation(automation: Automation) -> dict[str, Any] | None:
    """Queue the jobs for one run of an automation.

    :returns: a dict like {"job_id": <uuid>, "n_jobs": <int>}.
    """
    if automation.type == "forecasts":
        return _run_forecast_automation(automation)
    elif automation.type == "schedules":
        return _run_schedule_automation(automation)
    elif automation.type == "reports":
        return _run_report_automation(automation)
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


def _run_report_automation(automation: Automation) -> dict[str, Any] | None:
    if automation.generator is None:
        raise ValueError(
            f"Automation {automation.id} has no data generator to run (generator_id is not set)."
        )
    reporter = automation.generator.data_generator
    if not isinstance(reporter, Reporter):
        raise ValueError(
            f"Data source {automation.generator_id} of automation {automation.id} does not store a Reporter."
        )
    # The data generator instance is cached on the data source, which may be shared
    # by several automations, so wipe any parameter state from a previous run.
    reporter._parameters = None
    reporter.set_job_trigger("automation", automation_id=automation.id)
    parameters = prepare_report_parameters(
        dict(automation.parameters), automation.cronstr
    )
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
