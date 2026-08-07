"""
Logic around scheduling (jobs)
"""

from __future__ import annotations

from datetime import datetime, timedelta
import os
import sys
import importlib.util
from importlib.abc import Loader
from typing import Callable, Type
import inspect
from copy import deepcopy
from traceback import print_tb


import click
from flask import current_app
from isodate import duration_isoformat
from rq import get_current_job, Callback
from rq.exceptions import InvalidJobOperation, NoSuchJobError
from rq.job import Job, JobStatus
import timely_beliefs as tb
import pandas as pd
from sqlalchemy import select

from flexmeasures.data import db
from flexmeasures.data.models.planning import Scheduler, SchedulerOutputType
from flexmeasures.data.models.planning.storage import (
    StorageScheduler,
    SCHEDULING_RESULT_KEY,
)
from flexmeasures.data.models.planning.devices import INFLEXIBLE_DEVICE_KEYS
from flexmeasures.data.models.planning.exceptions import (
    InfeasibleProblemException,
    UpstreamSchedulingFailure,
)
from flexmeasures.data.models.planning.process import ProcessScheduler
from flexmeasures.data.services.scheduling_result import SchedulingJobResult
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.generic_assets import GenericAsset as Asset
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.schemas.scheduling import MultiSensorFlexModelSchema
from flexmeasures.data.utils import get_data_source, save_to_db
from flexmeasures.utils.time_utils import server_now
from flexmeasures.data.services.utils import (
    failed_job_reason,
    job_cache,
    get_asset_or_sensor_ref,
    get_asset_or_sensor_from_ref,
    get_scheduler_instance,
)


def load_custom_scheduler(scheduler_specs: dict | str) -> type:
    """
    Read in custom scheduling spec.
    Attempt to load the Scheduler class to use.

    The scheduler class should be derived from flexmeasures.data.models.planning.Scheduler.
    The scheduler class should have a class method named "compute".

    Example specs:

    {
        "module": "/path/to/module.py",  # or sthg importable, e.g. "package.module"
        "class": "NameOfSchedulerClass",
    }

    or if the scheduler is already subclassing flexmeasures.Scheduler, simply:

    "NameOfSchedulerClass"

    """
    if isinstance(scheduler_specs, dict):
        assert "module" in scheduler_specs, "scheduler specs have no 'module'."
        assert "class" in scheduler_specs, "scheduler specs have no 'class'"
    elif isinstance(scheduler_specs, str):
        scheduler_class = current_app.data_generators["scheduler"].get(scheduler_specs)
        if scheduler_class is None:
            raise ValueError(
                f"Scheduler {scheduler_specs} does not seem to be registered."
            )
        scheduler_specs = {
            "class": scheduler_class.__name__,
            "module": scheduler_class.__module__,
        }
    else:
        raise TypeError(
            f"Scheduler specs is {type(scheduler_specs)}, should be a dict or str"
        )

    scheduler_name = scheduler_specs["class"]

    # import module
    module_descr = scheduler_specs["module"]
    if os.path.exists(module_descr):
        spec = importlib.util.spec_from_file_location(scheduler_name, module_descr)
        assert spec, f"Could not load specs for scheduling module at {module_descr}."
        module = importlib.util.module_from_spec(spec)
        sys.modules[scheduler_name] = module
        assert isinstance(spec.loader, Loader)
        spec.loader.exec_module(module)
    else:  # assume importable module
        try:
            module = importlib.import_module(module_descr)
        except TypeError as te:
            current_app.logger.error(f"Cannot load {module_descr}: {te}.")
            raise
        except ModuleNotFoundError:
            current_app.logger.error(
                f"Attempted to import module {module_descr} (as it is not a valid file path), but it is not installed."
            )
            raise
        assert module, f"Module {module_descr} could not be loaded."

    # get scheduling function
    assert hasattr(
        module, scheduler_specs["class"]
    ), f"Module at {module_descr} has no class {scheduler_specs['class']}"

    scheduler_class = getattr(module, scheduler_specs["class"])
    schedule_function_name = "compute"
    if not hasattr(scheduler_class, schedule_function_name):
        raise NotImplementedError(
            f"No function {schedule_function_name} in {scheduler_class}. Cannot load custom scheduler."
        )
    return scheduler_class


def success_callback(job, connection, result, *args, **kwargs):
    queue = current_app.queues["scheduling"]
    orginal_job = Job.fetch(job.meta["original_job_id"], connection=connection)

    # requeue deferred jobs
    for dependent_job_ids in orginal_job.dependent_ids:
        queue.deferred_job_registry.requeue(dependent_job_ids)


# Meta flag marking a job that should still run when a job it depends on failed, so it can report on that failure.
# We deliberately do not use RQ's Dependency(allow_failure=True) for this: RQ enqueues such a job the moment its
# dependency fails, which would let a wrap-up job run while the failed subjob's fallback job is still pending,
# and report the chain as failed just before the fallback schedules the device after all.
RUNS_ON_CHAIN_FAILURE = "runs_on_chain_failure"


def _describe_scheduled_device(asset_or_sensor_ref: dict | None) -> str:
    """Describe the device that a scheduling job was scheduling, for use in a failure message.

    :param asset_or_sensor_ref: Serialized reference to an Asset or Sensor, as stored in a job's meta data.
    """
    if not asset_or_sensor_ref:
        return "an unknown device"
    asset_or_sensor = get_asset_or_sensor_from_ref(asset_or_sensor_ref)
    kind = asset_or_sensor_ref["class"].lower()
    if asset_or_sensor is None:
        return f"{kind} {asset_or_sensor_ref['id']}"
    if isinstance(asset_or_sensor, Sensor):
        return f"{kind} {asset_or_sensor.id} ({asset_or_sensor.generic_asset.name} - {asset_or_sensor.name})"
    return f"{kind} {asset_or_sensor.id} ({asset_or_sensor.name})"


def trigger_optional_fallback(job, connection, type, value, traceback):
    """Handle a failed scheduling job.

    A fallback schedule job is created when the error is of type InfeasibleProblemException,
    and the scheduler that failed defines a fallback scheduler.

    Schedulers are not required to define a fallback, though. Without one, the failure is cascaded to the jobs that depend on the failed job,
    so that a client polling one of them (such as the wrap-up job of a sequential schedule, whose id is what the trigger endpoint returns)
    reaches a terminal state with a reason, rather than waiting on a job that stays deferred forever.
    """

    job.meta["exception"] = value
    job.save_meta()

    if type is InfeasibleProblemException and _trigger_fallback_job(job):
        return

    # A failing fallback job leaves the dependents of the original job deferred, so cascade from that job instead.
    job_with_dependents = job
    original_job_id = job.meta.get("original_job_id")
    if original_job_id is not None:
        try:
            job_with_dependents = Job.fetch(original_job_id, connection=connection)
        except NoSuchJobError:
            current_app.logger.error(
                f"Original job with ID={original_job_id} (fallback Job ID={job.id}) not found, so its dependents cannot be failed."
            )
            return

    if not job_with_dependents.dependent_ids:
        return
    device = _describe_scheduled_device(job.meta.get("asset_or_sensor"))
    _cascade_failure_to_dependents(
        job_with_dependents,
        connection,
        reason=f"Scheduling {device} failed with {type.__name__}: {value}, so this schedule could not be computed either.",
    )


def _trigger_fallback_job(job) -> bool:
    """Create and enqueue a fallback schedule job for a failed scheduling job, if its scheduler defines a fallback.

    :param job: The failed scheduling job.
    :returns:   True if a fallback job was created, and False if the scheduler has no fallback.
    """
    asset_or_sensor = get_asset_or_sensor_from_ref(job.meta.get("asset_or_sensor"))

    scheduler_kwargs = job.meta["scheduler_kwargs"]

    # Deserialize start, end, resolution and belief_time
    # Workaround for https://github.com/Parallels/rq-dashboard/issues/510
    timezone = "UTC"
    if hasattr(asset_or_sensor, "timezone"):
        timezone = asset_or_sensor.timezone
    scheduler_kwargs["start"] = pd.Timestamp(scheduler_kwargs["start"]).tz_convert(
        timezone
    )
    scheduler_kwargs["end"] = pd.Timestamp(scheduler_kwargs["end"]).tz_convert(timezone)
    if isinstance(scheduler_kwargs.get("belief_time"), str):
        scheduler_kwargs["belief_time"] = pd.Timestamp(
            scheduler_kwargs["belief_time"]
        ).tz_convert(timezone)
    if isinstance(scheduler_kwargs.get("resolution"), str):
        scheduler_kwargs["resolution"] = pd.Timedelta(scheduler_kwargs["resolution"])

    if ("scheduler_specs" in job.kwargs) and (
        job.kwargs["scheduler_specs"] is not None
    ):
        scheduler_class: Type[Scheduler] = load_custom_scheduler(
            job.kwargs["scheduler_specs"]
        )
    else:
        scheduler_class: Type[Scheduler] = find_scheduler_class(asset_or_sensor)

    # only schedule a fallback schedule job if the original job has a fallback
    # mechanism
    if scheduler_class.fallback_scheduler_class is None:
        return False

    scheduler_class = scheduler_class.fallback_scheduler_class
    scheduler_specs = {
        "class": scheduler_class.__name__,
        "module": inspect.getmodule(scheduler_class).__name__,
    }

    fallback_job = create_scheduling_job(
        asset_or_sensor,
        force_new_job_creation=True,
        enqueue=False,
        scheduler_specs=scheduler_specs,
        success_callback=Callback(success_callback),
        **scheduler_kwargs,
    )

    # keep track of the id of the original (non-fallback) job
    fallback_job.meta["original_job_id"] = job.meta.get("original_job_id", job.id)
    fallback_job.save_meta()

    job.meta["fallback_job_id"] = fallback_job.id
    job.save_meta()
    current_app.queues["scheduling"].enqueue_job(fallback_job)
    return True


def _cascade_failure_to_dependents(job: Job, connection, reason: str) -> None:
    """Put the jobs that depend on a failed scheduling job into a terminal state, too.

    RQ only enqueues the dependents of a job that succeeded, so a failed job without a fallback would otherwise leave its dependents deferred forever,
    which leaves a client polling such a job (in particular the wrap-up job of a sequential schedule) without a terminal state or a reason.

    Jobs marked with RUNS_ON_CHAIN_FAILURE are queued rather than failed, so they can run and report on the failure.

    :param job:         The failed job whose dependents should be dealt with.
    :param connection:  Redis connection.
    :param reason:      Why the schedule could not be computed, naming the device that failed to be scheduled.
    """
    queue = current_app.queues["scheduling"]
    dependent_ids = list(job.dependent_ids)
    if not dependent_ids:
        return
    jobs_that_report_on_the_failure = []
    for dependent in Job.fetch_many(dependent_ids, connection=connection):
        if dependent is None:
            continue
        if dependent.get_status(refresh=True) != JobStatus.DEFERRED:
            continue
        if dependent.allow_dependency_failures:
            continue  # RQ enqueues a job that tolerates a failing dependency by itself
        if dependent.meta.get(RUNS_ON_CHAIN_FAILURE):
            jobs_that_report_on_the_failure.append(dependent)
            continue
        _fail_deferred_job(dependent, reason)
        _cascade_failure_to_dependents(dependent, connection, reason)

    # Only once the rest of the chain has reached a terminal state, let the reporting jobs run,
    # so that they see every subjob they report on in its final state.
    for dependent in jobs_that_report_on_the_failure:
        queue.deferred_job_registry.requeue(dependent.id)


def _fail_deferred_job(job: Job, reason: str) -> None:
    """Move a deferred job that will never run to a terminal failed state, recording why.

    :param job:     The deferred job.
    :param reason:  Why the schedule could not be computed, naming the device that failed to be scheduled.
    """
    queue = current_app.queues["scheduling"]
    job.meta["exception"] = UpstreamSchedulingFailure(reason)
    job.save_meta()
    job.set_status(JobStatus.FAILED)
    queue.deferred_job_registry.remove(job)
    queue.failed_job_registry.add(job, ttl=job.failure_ttl, exc_string=reason)


@job_cache("scheduling")
def create_scheduling_job(
    asset_or_sensor: Asset | Sensor | None = None,
    job_id: str | None = None,
    enqueue: bool = True,
    requeue: bool = False,
    force_new_job_creation: bool = False,
    scheduler_specs: dict | None = None,
    depends_on: Job | list[Job] | None = None,
    success_callback: Callable | None = None,
    **scheduler_kwargs,
) -> Job:
    """
    Create a new Job, which is queued for later execution.

    To support quick retrieval of the scheduling job, the job id is the unique entity address of the UDI event.
    That means one event leads to one job (i.e. actions are event driven).

    As a rule of thumb, keep arguments to the job simple, and deserializable.

    The life cycle of a scheduling job:
    1. A scheduling job is born here (in create_scheduling_job).
    2. It is run in make_schedule which writes results to the db.
    3. If an error occurs (and the worker is configured accordingly), handle_scheduling_exception comes in.

    Arguments:
    :param asset_or_sensor:         Asset or sensor for which the schedule is computed.
    :param job_id:                  Optionally, set a job id explicitly.
    :param enqueue:                 If True, enqueues the job in case it is new.
    :param requeue:                 If True, requeues the job in case it is not new and had previously failed
                                    (this argument is used by the @job_cache decorator).
    :param force_new_job_creation:  If True, this attribute forces a new job to be created (skipping cache).
    :param success_callback:        Callback function that runs on success
                                    (this argument is used by the @job_cache decorator).
    :returns:                       The job.

    """
    # We first create a scheduler and check if deserializing works, so the flex config is checked
    # and errors are raised before the job is enqueued (so users get a meaningful response right away).
    # Note: We should put only serializable scheduler_kwargs into the job!

    if scheduler_specs:
        scheduler_class: Type[Scheduler] = load_custom_scheduler(scheduler_specs)
    else:
        scheduler_class: Type[Scheduler] = find_scheduler_class(asset_or_sensor)

    scheduler = get_scheduler_instance(
        scheduler_class=scheduler_class,
        asset_or_sensor=asset_or_sensor,
        scheduler_params=scheduler_kwargs,
    )
    scheduler.collect_flex_config()
    scheduler_kwargs["flex_context"] = scheduler.flex_context
    scheduler_kwargs["flex_model"] = scheduler.flex_model
    scheduler.deserialize_config()

    # Set consumption_is_positive on output sensors now (at trigger time) so that any
    # attribute conflict raises an error immediately, before the job is enqueued.
    _set_flex_model_output_sensors_consumption_is_positive(scheduler.flex_model)

    asset_or_sensor = get_asset_or_sensor_ref(asset_or_sensor)
    job = Job.create(
        make_schedule,
        kwargs=dict(
            asset_or_sensor=asset_or_sensor,
            scheduler_specs=scheduler_specs,
            **scheduler_kwargs,
        ),
        id=job_id,
        connection=current_app.queues["scheduling"].connection,
        ttl=int(
            current_app.config.get(
                "FLEXMEASURES_JOB_TTL", timedelta(-1)
            ).total_seconds()
        ),
        result_ttl=int(
            current_app.config.get(
                "FLEXMEASURES_PLANNING_TTL", timedelta(-1)
            ).total_seconds()
        ),  # NB job.cleanup docs says a negative number of seconds means persisting forever
        on_failure=Callback(trigger_optional_fallback),
        on_success=success_callback,
        depends_on=depends_on,
    )

    job.meta["asset_or_sensor"] = asset_or_sensor
    job.meta["scheduler_kwargs"] = scheduler_kwargs

    # Serialize start, end, resolution and belief_time
    # Workaround for https://github.com/Parallels/rq-dashboard/issues/510
    job.meta["scheduler_kwargs"]["start"] = job.meta["scheduler_kwargs"][
        "start"
    ].isoformat()
    job.meta["scheduler_kwargs"]["end"] = job.meta["scheduler_kwargs"][
        "end"
    ].isoformat()
    if job.meta["scheduler_kwargs"].get("belief_time") is not None:
        job.meta["scheduler_kwargs"]["belief_time"] = job.meta["scheduler_kwargs"][
            "belief_time"
        ].isoformat()

    if job.meta["scheduler_kwargs"].get("resolution") is not None:
        job.meta["scheduler_kwargs"]["resolution"] = duration_isoformat(
            job.meta["scheduler_kwargs"]["resolution"]
        )

    job.save_meta()

    # in case the function enqueues it
    try:
        job_status = job.get_status(refresh=True)
    except InvalidJobOperation:
        job_status = None

    # with job_status=None, we ensure that only fresh new jobs are enqueued (otherwise, they should be requeued instead)
    if enqueue and not job_status:
        current_app.queues["scheduling"].enqueue_job(job)
        current_app.job_cache.add(
            asset_or_sensor["id"],
            job.id,
            queue="scheduling",
            asset_or_sensor_type=asset_or_sensor["class"].lower(),
        )

    return job


def cb_done_sequential_scheduling_job(jobs_ids: list[str]):
    """Wrap up a chain of sequential scheduling (sub)jobs.

    This job also runs when one of the subjobs failed without being rescued by a fallback (see RUNS_ON_CHAIN_FAILURE),
    in which case it fails, too, naming the devices that could not be scheduled.
    Its id is what the trigger endpoint hands to the client, so this is what gives that client a terminal state and a reason.

    TODO: maybe check if any of the subjobs used a fallback scheduler or accrued a relaxation penalty.

    :param jobs_ids:                    Ids of the scheduling subjobs in the chain.
    :raises UpstreamSchedulingFailure:  When any of the subjobs did not produce a schedule.
    """
    connection = current_app.queues["scheduling"].connection
    failed_devices, skipped_devices = [], []
    for job_id in jobs_ids:
        if _scheduling_job_succeeded(job_id, connection):
            continue
        try:
            job = Job.fetch(job_id, connection=connection)
        except NoSuchJobError:
            failed_devices.append(
                f"an unknown device (scheduling job {job_id} is no longer available)"
            )
            continue
        device = _describe_scheduled_device(job.meta.get("asset_or_sensor"))
        if isinstance(job.meta.get("exception"), UpstreamSchedulingFailure):
            # This device was never scheduled, because a device earlier in the chain failed.
            skipped_devices.append(device)
        else:
            reason = failed_job_reason(job) or f"job status is {job.get_status()}"
            failed_devices.append(f"{device}: {reason}")

    if not failed_devices and not skipped_devices:
        current_app.logger.info(
            "Sequential scheduling job finished its chain of subjobs."
        )
        return

    complaints = []
    if failed_devices:
        complaints.append(
            f"Sequential scheduling failed for {'; '.join(failed_devices)}."
        )
    if skipped_devices:
        complaints.append(
            f"As a result, no schedule was computed for {', '.join(skipped_devices)}."
        )
    raise UpstreamSchedulingFailure(" ".join(complaints))


def _scheduling_job_succeeded(job_id: str, connection) -> bool:
    """Tell whether a scheduling job produced a schedule, either by itself or through its fallback job.

    :param job_id:      Id of the scheduling job.
    :param connection:  Redis connection.
    """
    try:
        job = Job.fetch(job_id, connection=connection)
    except NoSuchJobError:
        return False
    if job.get_status(refresh=True) == JobStatus.FINISHED:
        return True
    fallback_job_id = job.meta.get("fallback_job_id")
    if fallback_job_id is None:
        return False
    return _scheduling_job_succeeded(fallback_job_id, connection)


def _add_inflexible_devices(flex_context: dict, sensors: list[Sensor]) -> None:
    """Add previously scheduled sensors to a (serialized) flex-context as inflexible devices.

    If the context already uses the deprecated ``inflexible-device-sensors`` key, bare
    sensor ids are appended there (their stored schedules are read according to each
    sensor's ``consumption_is_positive`` attribute, and mixing the deprecated key with
    the newer keys is rejected by FlexContextSchema.check_inflexible_devices).
    Otherwise, each sensor is routed to ``inflexible-consumption`` or
    ``inflexible-production`` according to that same attribute, which is also how the
    sign of the sensor's stored schedule was resolved when it was written
    (see :func:`_resolve_schedule_output_sign`).
    """
    already_listed = {
        entry["sensor"] if isinstance(entry, dict) else entry
        for key in INFLEXIBLE_DEVICE_KEYS
        for entry in (flex_context.get(key) or [])
    }
    for sensor in sensors:
        if sensor.id in already_listed:
            continue
        already_listed.add(sensor.id)
        if "inflexible-device-sensors" in flex_context:
            flex_context["inflexible-device-sensors"].append(sensor.id)
        elif sensor.get_attribute("consumption_is_positive", False):
            flex_context.setdefault("inflexible-consumption", []).append(
                {"sensor": sensor.id}
            )
        else:
            flex_context.setdefault("inflexible-production", []).append(
                {"sensor": sensor.id}
            )


@job_cache("scheduling")
def create_sequential_scheduling_job(
    asset: Asset,
    job_id: str | None = None,
    enqueue: bool = True,
    requeue: bool = False,
    force_new_job_creation: bool = False,
    scheduler_specs: dict | None = None,
    depends_on: list[Job] | None = None,
    success_callback: Callable | None = None,
    **scheduler_kwargs,
) -> Job:
    """Create a chain of underlying jobs, one for each device, with one additional job to wrap up.

    :param asset:                   Asset (e.g. a site) for which the schedule is computed.
    :param job_id:                  Optionally, set a job id explicitly.
    :param enqueue:                 If True, enqueues the job in case it is new.
    :param requeue:                 If True, requeues the job in case it is not new and had previously failed
                                    (this argument is used by the @job_cache decorator).
    :param force_new_job_creation:  If True, this attribute forces a new job to be created (skipping cache).
    :param success_callback:        Callback function that runs on success
                                    (this argument is used by the @job_cache decorator).
    :param scheduler_kwargs:        Dict containing start and end (both deserialized) the flex-context (serialized),
                                    and the flex-model (partially deserialized, see example below).
    :returns:                       The wrap-up job.

    Example of a partially deserialized flex-model per sensor:

        scheduler_kwargs["flex_model"] = [
            dict(
                sensor=<Sensor 5: power, unit: MW res.: 0:15:00>,
                sensor_flex_model={
                    'consumption-capacity': '10 kW',
                },
            ),
            dict(
                sensor=<deserialized sensor object>,
                sensor_flex_model=<still serialized flex-model>,
            ),
        ]

    """
    if enqueue is False:
        raise NotImplementedError(
            "See why: https://github.com/FlexMeasures/flexmeasures/pull/1313/files#r1971479492"
        )
    flex_model = scheduler_kwargs["flex_model"]
    jobs = []
    previous_sensors = []
    previous_job = depends_on
    for child_flex_model in flex_model:
        sensor = child_flex_model.pop("sensor")

        current_scheduler_kwargs = deepcopy(scheduler_kwargs)

        current_scheduler_kwargs["flex_model"] = child_flex_model["sensor_flex_model"]
        _add_inflexible_devices(
            current_scheduler_kwargs["flex_context"], previous_sensors
        )
        if "resolution" not in current_scheduler_kwargs:
            current_scheduler_kwargs["resolution"] = sensor.event_resolution
        current_scheduler_kwargs["asset_or_sensor"] = sensor

        job = create_scheduling_job(
            **current_scheduler_kwargs,
            scheduler_specs=scheduler_specs,
            requeue=requeue,
            job_id=job_id,
            enqueue=enqueue,
            depends_on=previous_job,
            force_new_job_creation=force_new_job_creation,
        )
        jobs.append(job)
        previous_sensors.append(sensor)
        previous_job = job

    # create job that triggers when the last job is done
    job = Job.create(
        func=cb_done_sequential_scheduling_job,
        args=([j.id for j in jobs],),
        depends_on=previous_job,
        ttl=int(
            current_app.config.get(
                "FLEXMEASURES_JOB_TTL", timedelta(-1)
            ).total_seconds()
        ),
        result_ttl=int(
            current_app.config.get(
                "FLEXMEASURES_PLANNING_TTL", timedelta(-1)
            ).total_seconds()
        ),  # NB job.cleanup docs says a negative number of seconds means persisting forever
        on_success=success_callback,
        connection=current_app.queues["scheduling"].connection,
    )
    job.meta["asset_or_sensor"] = get_asset_or_sensor_ref(asset)
    # This job should also run when a subjob failed, so it can report which devices could not be scheduled
    # (see _cascade_failure_to_dependents), instead of staying deferred forever.
    job.meta[RUNS_ON_CHAIN_FAILURE] = True
    job.save_meta()

    try:
        job_status = job.get_status(refresh=True)
    except InvalidJobOperation:
        job_status = None

    # with job_status=None, we ensure that only fresh new jobs are enqueued (otherwise, they should be requeued instead)
    if enqueue and not job_status:
        current_app.queues["scheduling"].enqueue_job(job)
        current_app.job_cache.add(
            asset.id,
            job.id,
            queue="scheduling",
            asset_or_sensor_type="asset",
        )
    return job


@job_cache("scheduling")
def create_simultaneous_scheduling_job(
    asset: Asset,
    job_id: str | None = None,
    enqueue: bool = True,
    requeue: bool = False,
    force_new_job_creation: bool = False,
    scheduler_specs: dict | None = None,
    depends_on: list[Job] | None = None,
    success_callback: Callable | None = None,
    **scheduler_kwargs,
) -> Job:
    """Create a single job to schedule all devices at once.

    :param asset:                   Asset (e.g. a site) for which the schedule is computed.
    :param job_id:                  Optionally, set a job id explicitly.
    :param enqueue:                 If True, enqueues the job in case it is new.
    :param requeue:                 If True, requeues the job in case it is not new and had previously failed
                                    (this argument is used by the @job_cache decorator).
    :param force_new_job_creation:  If True, this attribute forces a new job to be created (skipping cache).
    :param success_callback:        Callback function that runs on success
                                    (this argument is used by the @job_cache decorator).
    :param scheduler_kwargs:        Dict containing start and end (both deserialized) the flex-context (serialized),
                                    and the flex-model (partially deserialized, see example below).
    :returns:                       The wrap-up job.

    Example of a partially deserialized flex-model per sensor:

        scheduler_kwargs["flex_model"] = [
            dict(
                sensor=<Sensor 5: power, unit: MW res.: 0:15:00>,
                sensor_flex_model={
                    'consumption-capacity': '10 kW',
                },
            ),
            dict(
                sensor=<deserialized sensor object>,
                sensor_flex_model=<still serialized flex-model>,
            ),
        ]

    """
    # Convert (partially) deserialized fields back to serialized form
    scheduler_kwargs["flex_model"] = MultiSensorFlexModelSchema(many=True).dump(
        scheduler_kwargs["flex_model"]
    )

    job = create_scheduling_job(
        asset_or_sensor=asset,
        **scheduler_kwargs,
        scheduler_specs=scheduler_specs,
        requeue=requeue,
        job_id=job_id,
        enqueue=False,  # we enqueue all jobs later in this method
        depends_on=depends_on,
        success_callback=success_callback,
        force_new_job_creation=force_new_job_creation,
    )

    try:
        job_status = job.get_status(refresh=True)
    except InvalidJobOperation:
        job_status = None

    # with job_status=None, we ensure that only fresh new jobs are enqueued (otherwise, they should be requeued instead)
    if enqueue and not job_status:
        current_app.queues["scheduling"].enqueue_job(job)
        current_app.job_cache.add(
            asset.id,
            job.id,
            queue="scheduling",
            asset_or_sensor_type="asset",
        )

    return job


def _is_consumption_production_output(
    result: dict, asset_or_sensor: Asset | Sensor
) -> bool:
    """Return True when *result* is a dedicated consumption or production output schedule.

    A dedicated output schedule is one whose sensor is different from the main asset_or_sensor being scheduled,
    and whose name is ``"consumption_schedule"`` or ``"production_schedule"``.
    The main power schedule (including the backwards-compat wrapper for custom schedulers that return a plain Series)
    uses the same sensor as *asset_or_sensor* and is therefore not considered an output schedule.

    :param result:          Schedule output result dict with keys 'name', 'sensor', 'data'.
    :param asset_or_sensor: The Asset or Sensor being scheduled (main power sensor).
    :return:                True when the result targets a dedicated output sensor.
    """
    result_name = result.get("name", "")
    if result_name not in ("consumption_schedule", "production_schedule"):
        return False

    result_sensor = result["sensor"]
    # The main power schedule uses the same object as asset_or_sensor,
    # or – when asset_or_sensor is an Asset – one of its sensors.
    is_main = result_sensor == asset_or_sensor or (
        hasattr(asset_or_sensor, "generic_asset")
        and result_sensor.generic_asset == asset_or_sensor
    )
    return not is_main


def _set_flex_model_output_sensors_consumption_is_positive(
    flex_model: dict | list,
) -> None:
    """Set the ``consumption_is_positive`` attribute on consumption and production output sensors.

    Iterates over every device in *flex_model* and assigns::

        consumption sensor → consumption_is_positive = True
        production sensor  → consumption_is_positive = False

    A ``ValueError`` is raised immediately when the attribute is already present on a sensor
    but has the wrong value for the flex-model field that references it. Calling this function
    at job-creation time lets the API surface conflicts before any work is queued.

    :param flex_model: Deserialized flex model — either a single-device ``dict`` or a
                       ``list`` of per-device dicts. Consumption/production fields are
                       expected to be dicts with a ``"sensor"`` key.
    :raises ValueError: When ``consumption_is_positive`` is already set to the wrong value
                        for the given flex-model field.
    """
    models = flex_model if isinstance(flex_model, list) else [flex_model]
    for flex_model_d in models:
        consumption_field = flex_model_d.get("consumption")
        production_field = flex_model_d.get("production")
        consumption_sensor = (
            consumption_field.get("sensor")
            if isinstance(consumption_field, dict)
            else None
        )
        production_sensor = (
            production_field.get("sensor")
            if isinstance(production_field, dict)
            else None
        )
        for sensor, intended in [
            (consumption_sensor, True),
            (production_sensor, False),
        ]:
            if sensor is None:
                continue
            field_name = "consumption_schedule" if intended else "production_schedule"
            existing = sensor.attributes.get("consumption_is_positive")
            if existing is not None and existing != intended:
                raise ValueError(
                    f"Sensor {sensor} already has `consumption_is_positive={existing}`, "
                    f"which conflicts with the '{field_name}' output schedule "
                    f"(expected `consumption_is_positive={intended}`). "
                    f"Remove or correct the attribute before running the scheduler."
                )
            sensor.attributes["consumption_is_positive"] = intended


def _set_output_sensor_consumption_is_positive(
    result: dict, asset_or_sensor: Asset | Sensor
) -> None:
    """Set the ``consumption_is_positive`` attribute on a dedicated output sensor.

    For consumption output sensors the attribute is set to ``True`` (consumption is stored as
    positive values). For production output sensors it is set to ``False`` (production is stored
    as positive values, consumption as negative).

    The function is a no-op when *result* is not a dedicated consumption/production output
    schedule (as determined by :func:`_is_consumption_production_output`).

    A ``ValueError`` is raised when the attribute is already present on the sensor but points
    in the wrong direction for the flex-model field being used. This check runs *before* any
    data are written so that the error surfaces as early as possible.

    :param result:          Schedule output result dict with keys ``'name'``, ``'sensor'``,
                            ``'data'``.
    :param asset_or_sensor: The Asset or Sensor being scheduled (main power sensor).
    :raises ValueError:     When ``consumption_is_positive`` is already set to the wrong value
                            for the given flex-model field.
    """
    if not _is_consumption_production_output(result, asset_or_sensor):
        return

    result_sensor = result["sensor"]
    result_name = result.get("name", "")
    # consumption_schedule → True (consumption positive)
    # production_schedule  → False (production positive, i.e. consumption negative)
    intended = result_name == "consumption_schedule"
    existing = result_sensor.attributes.get("consumption_is_positive")
    if existing is not None and existing != intended:
        raise ValueError(
            f"Sensor {result_sensor} already has `consumption_is_positive={existing}`, "
            f"which conflicts with the '{result_name}' output schedule "
            f"(expected `consumption_is_positive={intended}`). "
            f"Remove or correct the attribute before re-running the scheduler."
        )
    # Direct attribute assignment works for both new and existing attributes.
    # set_attribute() is intentionally not used here because it silently
    # no-ops when the attribute does not yet exist.
    result_sensor.attributes["consumption_is_positive"] = intended


def _resolve_schedule_output_sign(
    result: dict,
    asset_or_sensor: Asset | Sensor,
) -> int:
    """Determine the sign multiplier for a schedule output result.

    Returns 1 (no sign change) or -1 (invert sign) depending on whether the result
    is a power schedule that needs sign conversion so that production is stored as positive
    values in the database.

    The scheduler always produces consumption-positive values. For sensors that carry
    ``consumption_is_positive=True`` (including consumption output sensors) no conversion
    is needed. For sensors with ``consumption_is_positive=False`` (production output sensors
    and the default convention for main power sensors) the sign is inverted.

    .. note::
        For consumption/production output sensors the ``consumption_is_positive`` attribute
        must be set before this function is called. It is set eagerly at job-creation time
        by :func:`_set_flex_model_output_sensors_consumption_is_positive`, and again (as a
        safety-net for direct :func:`make_schedule` calls) by
        :func:`_set_output_sensor_consumption_is_positive` earlier in the same loop iteration.

    :param result:          Schedule output result dict with keys 'name', 'sensor', 'data'.
    :param asset_or_sensor: The Asset or Sensor being scheduled (main power sensor).
    :return:                Sign multiplier: 1 (keep sign) or -1 (invert sign).
    """
    result_sensor = result["sensor"]

    # Apply sign inversion for power sensors that record production as positive values
    # (i.e. those that do not carry consumption_is_positive=True).
    if result_sensor.measures_power and not result_sensor.get_attribute(
        "consumption_is_positive", False
    ):
        return -1

    return 1


def make_schedule(  # noqa: C901
    sensor_id: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    resolution: timedelta | None = None,
    asset_or_sensor: dict | None = None,
    belief_time: datetime | None = None,
    flex_model: dict | None = None,
    flex_context: dict | None = None,
    flex_config_has_been_deserialized: bool = False,
    scheduler_specs: dict | None = None,
    dry_run: bool = False,
    **scheduler_kwargs: dict,
) -> dict:
    """
    This function computes a schedule. It returns a dict, empty on schedulers
    that don't (yet) produce further analysis. If the scheduler produced soft
    state-of-charge constraint analysis (see ``SchedulingJobResult``), the dict
    instead holds that analysis under ``unresolved`` and ``resolved`` keys.

    It can be queued as a job (see create_scheduling_job).
    In that case, it will probably run on a different FlexMeasures node than where the job is created.
    In any case, this function expects flex_model and flex_context to not have been deserialized yet.

    This is what this function does:
    - Find out which scheduler should be used & compute the schedule
    - Turn scheduled values into beliefs
    - Save the beliefs to the database, unless dry_run is False
    """
    # https://docs.sqlalchemy.org/en/13/faq/connections.html#how-do-i-use-engines-connections-sessions-with-python-multiprocessing-or-os-fork
    db.engine.dispose()

    if sensor_id is not None:
        current_app.logger.warning(
            "The `sensor_id` keyword argument is deprecated. Please, consider using the argument `asset_or_sensor`."
        )
        asset_or_sensor = {"class": "Sensor", "id": sensor_id}

    asset_or_sensor: Asset | Sensor = get_asset_or_sensor_from_ref(asset_or_sensor)

    rq_job = get_current_job()
    if rq_job:
        click.echo(
            "Running Scheduling Job %s: %s, from %s to %s"
            % (rq_job.id, asset_or_sensor, start, end)
        )

    if scheduler_specs:
        scheduler_class: Type[Scheduler] = load_custom_scheduler(scheduler_specs)
    else:
        scheduler_class: Type[Scheduler] = find_scheduler_class(asset_or_sensor)

    data_source_info = scheduler_class.get_data_source_info()

    if belief_time is None:
        belief_time = server_now()

    scheduler_params = dict(
        start=start,
        end=end,
        resolution=resolution,
        belief_time=belief_time,
        flex_model=flex_model,
        flex_context=flex_context,
        return_multiple=True,
        **scheduler_kwargs,
    )

    scheduler: Scheduler = get_scheduler_instance(
        scheduler_class=scheduler_class,
        asset_or_sensor=asset_or_sensor,
        scheduler_params=scheduler_params,
    )

    if flex_config_has_been_deserialized:
        scheduler.config_deserialized = True

    # we get the default scheduler info in case it fails in the compute step
    if rq_job:
        rq_job.meta["scheduler_info"] = scheduler.info

    consumption_schedule: SchedulerOutputType = scheduler.compute()

    # in case we are getting a custom Scheduler that hasn't implemented the multiple output return
    # this should only be called whenever the Scheduler applies to the Sensor.
    if isinstance(consumption_schedule, pd.Series):
        assert isinstance(asset_or_sensor, Sensor), ""
        consumption_schedule = [
            {
                "name": "consumption_schedule",
                "data": consumption_schedule,
                "sensor": asset_or_sensor,
            }
        ]

    if rq_job:
        click.echo("Job %s made schedule." % rq_job.id)
        rq_job.meta["scheduler_info"] = scheduler.info

    data_source = get_data_source(
        data_source_name=data_source_info["name"],
        data_source_model=data_source_info["model"],
        data_source_version=data_source_info["version"],
        data_source_type="scheduler",
    )

    # saving info on the job, so the API for a job can look the data up
    if rq_job:
        data_source_info["id"] = data_source.id
        rq_job.meta["data_source_info"] = data_source_info
        rq_job.save_meta()

    # Save any result that specifies a sensor to save it to
    scheduling_result_dict: dict = SchedulingJobResult().to_dict()
    num_beliefs_created = 0
    for result in consumption_schedule:
        if result.get("name") == SCHEDULING_RESULT_KEY:
            scheduling_result_dict = result["data"].to_dict()
            continue
        if rq_job and result.get("name") == "commitment_costs":
            rq_job.meta["scheduler_info"]["commitment_costs"] = result["data"]
            continue
        if "sensor" not in result:
            continue

        # Ensure consumption_is_positive is set before resolving the sign.
        # At job-creation time this is already done eagerly; calling it here again
        # acts as a safety net for direct make_schedule invocations and raises a
        # ValueError on attribute conflicts before any data are written.
        _set_output_sensor_consumption_is_positive(result, asset_or_sensor)

        sign = _resolve_schedule_output_sign(result, asset_or_sensor)

        ts_value_schedule = [
            TimedBelief(
                event_start=dt,
                belief_time=belief_time,
                event_value=sign * value,
                sensor=result["sensor"],
                source=data_source,
            )
            for dt, value in result["data"].items()
        ]  # For consumption schedules, positive values denote consumption. For the db, consumption is negative
        bdf = tb.BeliefsDataFrame(ts_value_schedule)

        # Set the correct event resolution
        if resolution is not None and bdf.event_resolution != timedelta(0):
            bdf.event_resolution = resolution

            # Resample from the scheduling resolution to the sensor resolution
            # todo: move this into save_to_db
            bdf = bdf.resample_events(bdf.sensor.event_resolution)

        if not dry_run:
            save_to_db(bdf)
            num_beliefs_created += len(bdf)
        else:
            print(
                f"\nNot saving schedule for sensor `{bdf.sensor}` to the database (because of dry-run), but this is what I computed:\n{bdf}"
            )

    # num_beliefs_created counts beliefs actually saved; in dry_run mode this is always 0
    scheduling_result_dict["num-beliefs"] = num_beliefs_created

    if not dry_run:
        scheduler.persist_flex_model()
        db.session.commit()

    return scheduling_result_dict


def find_scheduler_class(asset_or_sensor: Asset | Sensor) -> type:
    """
    Find out which scheduler to use, given an asset or sensor.
    This will morph into a logic store utility, and schedulers should be registered for asset types there,
    instead of this fixed lookup logic.
    """

    # Choose which algorithm to use  TODO: unify loading this into a func store concept
    # first try to look if there's a "custom-scheduler" defined
    if "custom-scheduler" in asset_or_sensor.attributes:
        scheduler_specs = asset_or_sensor.attributes.get("custom-scheduler")
        scheduler_class = load_custom_scheduler(scheduler_specs)
        return scheduler_class

    if isinstance(asset_or_sensor, Sensor):
        asset = asset_or_sensor.generic_asset
    else:
        asset = asset_or_sensor

    if asset.generic_asset_type.name in ("process", "load"):
        scheduler_class = ProcessScheduler
    else:
        scheduler_class = StorageScheduler

    return scheduler_class


def handle_scheduling_exception(job, exc_type, exc_value, traceback):
    """
    Store exception as job meta data.
    """
    click.echo(
        "HANDLING RQ SCHEDULING WORKER EXCEPTION: %s:%s\n" % (exc_type, exc_value)
    )

    print_tb(traceback)
    job.meta["exception"] = exc_value
    job.save_meta()


def get_data_source_for_job(job: Job, type: str = "scheduler") -> DataSource | None:
    """
    Try to find the data source linked by this scheduling or forecasting job.

    We expect that enough info on the source was placed in the meta dict, either:
    - the DataSource ID itself (i.e. the normal situation), or
    - enough info to facilitate a DataSource query (as a fallback).
    """
    data_source_info = job.meta.get("data_source_info")
    if data_source_info and "id" in data_source_info:
        # this is the expected outcome
        return db.session.get(DataSource, data_source_info["id"])
    if data_source_info is None:
        raise ValueError(
            f"Cannot look up {type} data without knowing the full data_source_info (version)."
        )
    sources = db.session.scalars(
        select(DataSource)
        .filter_by(
            type=type,
            **data_source_info,
        )
        .order_by(DataSource.version.desc())
    ).all()  # Might still be more than one, e.g. per user
    if len(sources) == 0:
        return None
    return sources[0]
