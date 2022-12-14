from datetime import datetime, timedelta
from typing import Optional
import os
import sys
import importlib.util
from importlib.abc import Loader
from rq.job import Job

from flask import current_app
import click
from rq import get_current_job
import timely_beliefs as tb

from flexmeasures.data import db
from flexmeasures.data.models.planning import Scheduler
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.utils import get_data_source, save_to_db
from flexmeasures.utils.time_utils import server_now

"""
The life cycle of a scheduling job:
1. A scheduling job is born in create_scheduling_job.
2. It is run in make_schedule which writes results to the db.
3. If an error occurs (and the worker is configured accordingly), handle_scheduling_exception comes in.
   This might re-enqueue the job or try a different model (which creates a new job).
"""


def create_scheduling_job(
    sensor_id: int,
    job_id: Optional[str] = None,
    enqueue: bool = True,
    **scheduler_kwargs,
) -> Job:
    """
    Create a new Job, which is queued for later execution.

    To support quick retrieval of the scheduling job, the job id is the unique entity address of the UDI event.
    That means one event leads to one job (i.e. actions are event driven).

    As a rule of thumb, keep arguments to the job simple, and deserializable.
    """
    job = Job.create(
        make_schedule,
        kwargs=dict(
            sensor_id=sensor_id, **scheduler_kwargs
        ),  # TODO: we're passing sensor objects in flex_context. Passing IDs would be cleaner to avoid potential db sessions confusion.
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
    if enqueue:
        current_app.queues["scheduling"].enqueue_job(job)
    return job


def make_schedule(
    sensor_id: int,
    start: datetime,
    end: datetime,
    resolution: timedelta,
    belief_time: Optional[datetime] = None,
    flex_model: Optional[dict] = None,
    flex_context: Optional[dict] = None,
) -> bool:
    """
    This function is meant to be queued as a job. It returns True if it ran successfully.

    Note: This function thus potentially runs on a different FlexMeasures node than where the job is created.

    This is what this function does
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
    data_source_info = get_data_source_info_by_scheduler_class(scheduler_class)

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
    consumption_schedule = scheduler.compute_schedule()
    if rq_job:
        click.echo("Job %s made schedule." % rq_job.id)

    data_source = get_data_source(
        data_source_name=data_source_info["name"],
        data_source_model=data_source_info["model"],
        data_source_version=data_source_info["version"],
        data_source_type="scheduling script",
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
            current_app.log.error(f"Cannot load {module_descr}: {te}.")
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
    schedule_function_name = "compute_schedule"
    if not hasattr(scheduler_class, schedule_function_name):
        raise NotImplementedError(
            f"No function {schedule_function_name} in {scheduler_class}. Cannot load custom scheduler."
        )
    return scheduler_class


def get_data_source_info_by_scheduler_class(scheduler_class: type) -> dict:
    """
    Create and return the data source info, from which a data source lookup/creation is possible.
    See for instance get_data_source_for_job().
    """
    source_info = dict(
        model=scheduler_class.__name__, version="1", name="Unknown author"
    )  # default

    if hasattr(scheduler_class, "__version__"):
        source_info["version"] = str(scheduler_class.__version__)
    else:
        current_app.logger.warning(
            f"Scheduler {scheduler_class.__name__} loaded, but has no __version__ attribute."
        )
    if hasattr(scheduler_class, "__author__"):
        source_info["name"] = str(scheduler_class.__author__)
    else:
        current_app.logger.warning(
            f"Scheduler {scheduler_class.__name__} loaded, but has no __author__ attribute."
        )
    return source_info


def handle_scheduling_exception(job, exc_type, exc_value, traceback):
    """
    Store exception as job meta data.
    """
    click.echo("HANDLING RQ WORKER EXCEPTION: %s:%s\n" % (exc_type, exc_value))
    job.meta["exception"] = exc_value
    job.save_meta()


def get_data_source_for_job(
    job: Optional[Job], sensor: Optional[Sensor] = None
) -> Optional[DataSource]:
    """
    Try to find the data source linked by this scheduling job.

    We expect that enough info on the source was placed in the meta dict.
    For a transition period, we might have to guess a bit.
    TODO: Afterwards, this can be lighter. We should also expect a job and no sensor is needed,
          once API v1.3 is deprecated.
    """
    data_source_info = None
    if job:
        data_source_info = job.meta.get("data_source_info")
        if data_source_info and "id" in data_source_info:
            return DataSource.query.get(data_source_info["id"])
    if data_source_info is None and sensor:
        data_source_info = dict(name="Seita", model="StorageScheduler")
        # TODO: change to raise later (v0.13) - all scheduling jobs now get full info
        current_app.logger.warning(
            "Looking up scheduling data without knowing full data_source_info (version). This is deprecated soon. Please specify a job id as event or switch to API v3."
        )
    scheduler_sources = (
        DataSource.query.filter_by(
            type="scheduling script",
            **data_source_info,
        )
        .order_by(DataSource.version.desc())
        .all()
    )  # Might still be more than one, e.g. per user
    if len(scheduler_sources) == 0:
        return None
    return scheduler_sources[0]
