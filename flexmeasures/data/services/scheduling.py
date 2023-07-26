"""
Logic around scheduling (jobs)
"""

from __future__ import annotations

from datetime import datetime, timedelta
import os
import sys
import importlib.util
from importlib.abc import Loader

from flask import current_app
import click
from rq import get_current_job
from rq.job import Job
import timely_beliefs as tb

from flexmeasures.data import db
from flexmeasures.data.models.planning import Scheduler
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.data.models.planning.process import ProcessScheduler
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.utils import get_data_source, save_to_db
from flexmeasures.utils.time_utils import server_now
from flexmeasures.data.services.utils import job_cache


@job_cache("scheduling")
def create_scheduling_job(
    sensor: Sensor,
    job_id: str | None = None,
    enqueue: bool = True,
    requeue: bool = False,
    force_new_job_creation: bool = False,
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
    :param sensor:                  sensor for which the schedule is computed
    :param job_id:                  optionally, set a job id explicitly
    :param enqueue:                 if True, enqueues the job in case it is new
    :param requeue:                 if True, requeues the job in case it is not new and had previously failed
                                    (this argument is used by the @job_cache decorator)
    :param force_new_job_creation:  if True, this attribute forces a new job to be created (skipping cache)
                                    (this argument is used by the @job_cache decorator)
    :returns: the job

    """
    # We first create a scheduler and check if deserializing works, so the flex config is checked
    # and errors are raised before the job is enqueued (so users get a meaningful response right away).
    # Note: We are putting still serialized scheduler_kwargs into the job!
    scheduler = find_scheduler_class(sensor)(sensor=sensor, **scheduler_kwargs)
    scheduler.deserialize_config()

    job = Job.create(
        make_schedule,
        kwargs=dict(sensor_id=sensor.id, **scheduler_kwargs),
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
    )

    # in case the function enqueues it
    job_status = job.get_status(refresh=True)

    # with job_status=None, we ensure that only fresh new jobs are enqueued (in the contrary they should be requeued)
    if enqueue and not job_status:
        current_app.queues["scheduling"].enqueue_job(job)

    return job


def make_schedule(
    sensor_id: int,
    start: datetime,
    end: datetime,
    resolution: timedelta,
    belief_time: datetime | None = None,
    flex_model: dict | None = None,
    flex_context: dict | None = None,
    flex_config_has_been_deserialized: bool = False,
) -> bool:

    """
    This function computes a schedule. It returns True if it ran successfully.

    It can be queued as a job (see create_scheduling_job).
    In that case, it will probably run on a different FlexMeasures node than where the job is created.
    In any case, this function expects flex_model and flex_context to not have been deserialized yet.

    This is what this function does:
    - Find out which scheduler should be used & compute the schedule
    - Turn scheduled values into beliefs and save them to db
    """
    # https://docs.sqlalchemy.org/en/13/faq/connections.html#how-do-i-use-engines-connections-sessions-with-python-multiprocessing-or-os-fork
    db.engine.dispose()

    sensor = Sensor.query.filter_by(id=sensor_id).one_or_none()

    rq_job = get_current_job()
    if rq_job:
        click.echo(
            "Running Scheduling Job %s: %s, from %s to %s"
            % (rq_job.id, sensor, start, end)
        )

    scheduler_class = find_scheduler_class(sensor)
    data_source_info = scheduler_class.get_data_source_info()

    if belief_time is None:
        belief_time = server_now()
    scheduler: Scheduler = scheduler_class(
        sensor,
        start,
        end,
        resolution,
        belief_time=belief_time,
        flex_model=flex_model,
        flex_context=flex_context,
    )
    if flex_config_has_been_deserialized:
        scheduler.config_deserialized = True
    consumption_schedule = scheduler.compute()
    if rq_job:
        click.echo("Job %s made schedule." % rq_job.id)

    data_source = get_data_source(
        data_source_name=data_source_info["name"],
        data_source_model=data_source_info["model"],
        data_source_version=data_source_info["version"],
        data_source_type="scheduler",
    )

    # saving info on the job, so the API for a job can look the data up
    data_source_info["id"] = data_source.id
    if rq_job:
        rq_job.meta["data_source_info"] = data_source_info
        rq_job.save_meta()

    ts_value_schedule = [
        TimedBelief(
            event_start=dt,
            belief_time=belief_time,
            event_value=-value,
            sensor=sensor,
            source=data_source,
        )
        for dt, value in consumption_schedule.items()
    ]  # For consumption schedules, positive values denote consumption. For the db, consumption is negative
    bdf = tb.BeliefsDataFrame(ts_value_schedule)
    save_to_db(bdf)

    scheduler.persist_flex_model()
    db.session.commit()

    return True


def find_scheduler_class(sensor: Sensor) -> type:
    """
    Find out which scheduler to use, given a sensor.
    This will morph into a logic store utility, and schedulers should be registered for asset types there,
    instead of this fixed lookup logic.
    """
    # Choose which algorithm to use  TODO: unify loading this into a func store concept
    if "custom-scheduler" in sensor.attributes:
        scheduler_specs = sensor.attributes.get("custom-scheduler")
        scheduler_class = load_custom_scheduler(scheduler_specs)
    elif sensor.generic_asset.generic_asset_type.name in (
        "battery",
        "one-way_evse",
        "two-way_evse",
    ):
        scheduler_class = StorageScheduler
    elif sensor.generic_asset.generic_asset_type.name in ("process", "load"):
        scheduler_class = ProcessScheduler
    else:
        raise ValueError(
            "Scheduling is not (yet) supported for asset type %s."
            % sensor.generic_asset.generic_asset_type
        )
    return scheduler_class


def load_custom_scheduler(scheduler_specs: dict) -> type:
    """
    Read in custom scheduling spec.
    Attempt to load the Scheduler class to use.

    The scheduler class should be derived from flexmeasures.data.models.planning.Scheduler.
    The Callable is assumed to be named "schedule".

    Example specs:

    {
        "module": "/path/to/module.py",  # or sthg importable, e.g. "package.module"
        "class": "NameOfSchedulerClass",
    }

    """
    assert isinstance(
        scheduler_specs, dict
    ), f"Scheduler specs is {type(scheduler_specs)}, should be a dict"
    assert "module" in scheduler_specs, "scheduler specs have no 'module'."
    assert "class" in scheduler_specs, "scheduler specs have no 'class'"

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


def handle_scheduling_exception(job, exc_type, exc_value, traceback):
    """
    Store exception as job meta data.
    """
    click.echo(
        "HANDLING RQ SCHEDULING WORKER EXCEPTION: %s:%s\n" % (exc_type, exc_value)
    )
    # from traceback import print_tb
    # print_tb(traceback)
    job.meta["exception"] = exc_value
    job.save_meta()


def get_data_source_for_job(job: Job | None) -> DataSource | None:
    """
    Try to find the data source linked by this scheduling job.

    We expect that enough info on the source was placed in the meta dict.
    This only happened with v0.12. For a transition period, we might have to support older jobs who haven't got that info.
    TODO: We should expect a job, once API v1.3 is deprecated.
    """
    data_source_info = None
    if job:
        data_source_info = job.meta.get("data_source_info")
        if (
            data_source_info and "id" in data_source_info
        ):  # this is the expected outcome
            return DataSource.query.get(data_source_info["id"])
    if data_source_info is None:
        data_source_info = dict(name="Seita", model="StorageScheduler")
        # TODO: change to raise later (v0.13) - all scheduling jobs now get full info
        current_app.logger.warning(
            "Looking up scheduling data without knowing full data_source_info (version). This is deprecated soon. Please specify a job id as event or switch to API v3."
        )
    scheduler_sources = (
        DataSource.query.filter_by(
            type="scheduler",
            **data_source_info,
        )
        .order_by(DataSource.version.desc())
        .all()
    )  # Might still be more than one, e.g. per user
    if len(scheduler_sources) == 0:
        return None
    return scheduler_sources[0]
