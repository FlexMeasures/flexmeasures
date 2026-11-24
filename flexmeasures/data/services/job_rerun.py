"""Deciding who may re-run a failed background job, and re-running it."""

from __future__ import annotations

from marshmallow import ValidationError
from rq.exceptions import InvalidJobOperation
from rq.job import Job, JobStatus
from werkzeug.exceptions import Forbidden, Unauthorized

from flexmeasures.auth.policy import check_access
from flexmeasures.data import db
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.data_generators import (
    check_sensor_access,
    resolve_data_generator_sensors,
)
from flexmeasures.data.services.utils import get_asset_or_sensor_from_ref


class JobNotRerunnable(ValueError):
    """The job cannot be re-run from the API, whoever asks."""


class JobNotFailed(ValueError):
    """Only a failed job can be re-run."""


def _job_sensor(job: Job) -> Sensor | None:
    """The sensor a forecasting job computes for, as far as the job names one."""
    sensor_id = job.meta.get("sensor_id")
    if sensor_id is None:
        forecast_kwargs = job.meta.get("forecast_kwargs", {})
        if isinstance(forecast_kwargs, dict):
            sensor_id = forecast_kwargs.get("sensor_id")
    if sensor_id is None:
        sensor_id = job.kwargs.get("sensor_id")
    if sensor_id is None:
        return None
    return db.session.get(Sensor, sensor_id)


def _check_schedule_rerun_access(job: Job) -> GenericAsset:
    """Require the right to trigger schedules on the asset or sensor the schedule was computed for."""
    ref = job.meta.get("asset_or_sensor") or job.kwargs.get("asset_or_sensor")
    asset_or_sensor = get_asset_or_sensor_from_ref(ref) if ref else None
    if asset_or_sensor is None:
        raise JobNotRerunnable(f"Job {job.id} names no asset or sensor to schedule.")
    check_access(asset_or_sensor, "trigger-schedules")
    if isinstance(asset_or_sensor, Sensor):
        return asset_or_sensor.generic_asset
    return asset_or_sensor


def _check_forecast_rerun_access(job: Job) -> GenericAsset:
    """Require the right to trigger forecasts on the sensor the forecast is for."""
    sensor = _job_sensor(job)
    if sensor is None:
        raise JobNotRerunnable(f"Job {job.id} names no sensor to forecast.")
    check_access(sensor, "trigger-forecasts")
    return sensor.generic_asset


def _check_report_rerun_access(job: Job) -> GenericAsset:
    """Require what triggering the same report through the API requires.

    That is the right to trigger reports on the asset of each output sensor,
    read access to each input sensor, and the right to record data on each output sensor.
    The reporter's parameters may have been valid when the job was queued, and still be refused now, for example after a change of permissions.
    """
    source = db.session.get(DataSource, job.kwargs.get("data_source_id"))
    reporter = source.data_generator if source is not None else None
    if reporter is None:
        raise JobNotRerunnable(f"Job {job.id} names no reporter to run.")
    try:
        parameters = reporter._parameters_schema.load(job.kwargs.get("parameters", {}))
    except ValidationError as exc:
        raise JobNotRerunnable(
            f"The parameters of job {job.id} are no longer valid: {exc.messages}"
        ) from exc
    report_sensors = resolve_data_generator_sensors(reporter, parameters)
    if not report_sensors["output_sensors"]:
        raise JobNotRerunnable(f"Job {job.id} names no sensor to report on.")
    for output_sensor in report_sensors["output_sensors"]:
        check_access(output_sensor.generic_asset, "trigger-reports")
    check_sensor_access(
        report_sensors["input_sensors"], report_sensors["output_sensors"]
    )
    return report_sensors["output_sensors"][0].generic_asset


def _check_upload_rerun_access(job: Job) -> GenericAsset:
    """Require the right to record data on the sensor the upload is for, which the upload itself needs."""
    sensor = _job_sensor(job)
    if sensor is None:
        raise JobNotRerunnable(f"Job {job.id} names no sensor to record data on.")
    check_access(sensor, "post-data")
    return sensor.generic_asset


def _check_automation_rerun_access(job: Job) -> GenericAsset:
    """Require the right to manage automations on the asset of the automation, which triggering it needs."""
    automation_id = job.kwargs.get("automation_id")
    automation = (
        db.session.get(Automation, automation_id) if automation_id is not None else None
    )
    if automation is None:
        raise JobNotRerunnable(f"Job {job.id} names no automation to run.")
    check_access(automation.asset, "manage-automations")
    return automation.asset


def _is_plugin_automation_job(job: Job) -> bool:
    """Whether the job runs an automation of a type defined by a plugin, which can be on any queue."""
    from flexmeasures.data.automations import execute_automation_job

    return (
        job.func_name
        == f"{execute_automation_job.__module__}.{execute_automation_job.__qualname__}"
    )


RERUN_ACCESS_CHECKS = {
    "scheduling": _check_schedule_rerun_access,
    "forecasting": _check_forecast_rerun_access,
    "reporting": _check_report_rerun_access,
    "ingestion": _check_upload_rerun_access,
}


def check_job_rerun_access(job: Job) -> GenericAsset:
    """Require that the current user may re-run this job, and return the asset to log the re-run on.

    The permission follows the type of job, as it does when triggering one:
    trigger-schedules for schedules, trigger-forecasts for forecasts, trigger-reports for reports,
    post-data on the sensor for uploads, and manage-automations on the asset for jobs of plugin automations, whichever queue they run on.

    :raises JobNotRerunnable: if the job is of an unknown type, or names no asset or sensor.
    :raises Forbidden:        if the current user may not re-run it.
    """
    if _is_plugin_automation_job(job):
        return _check_automation_rerun_access(job)
    check = RERUN_ACCESS_CHECKS.get(job.origin)
    if check is None:
        raise JobNotRerunnable(
            f"Jobs on the '{job.origin}' queue cannot be re-run from here."
        )
    return check(job)


def can_rerun_job(job: Job, status: JobStatus | str | None = None) -> bool:
    """Whether the current user may re-run this job now, so that the UI only offers it when it would work."""
    if status is None:
        status = job.get_status(refresh=False)
    if status != JobStatus.FAILED:
        return False
    try:
        check_job_rerun_access(job)
    except (JobNotRerunnable, Forbidden, Unauthorized):
        return False
    return True


def rerun_failed_job(job: Job) -> None:
    """Queue a failed job again, under the same job ID.

    Keeping the ID keeps the job indexed under its assets and sensors, and keeps its dependents attached.

    :raises JobNotFailed: if the job has not failed, or is no longer in the queue's registry of failed jobs.
    """
    if job.get_status() != JobStatus.FAILED:
        raise JobNotFailed(f"Job {job.id} has not failed, so it cannot be re-run.")
    try:
        job.requeue()
    except InvalidJobOperation as exc:
        raise JobNotFailed(
            f"Job {job.id} is no longer listed as failed, so it cannot be re-run."
        ) from exc
