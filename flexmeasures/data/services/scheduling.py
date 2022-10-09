from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Callable
import os
import sys
import importlib.util
from importlib.abc import Loader

from flask import current_app
import click
import numpy as np
import pandas as pd
from rq import get_current_job
from rq.job import Job
import timely_beliefs as tb

from flexmeasures.data import db
from flexmeasures.data.models.planning.battery import schedule_battery
from flexmeasures.data.models.planning.charging_station import schedule_charging_station
from flexmeasures.data.models.planning.utils import initialize_series
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.utils import get_data_source, save_to_db

"""
The life cycle of a scheduling job:
1. A scheduling job is born in create_scheduling_job.
2. It is run in make_schedule which writes results to the db.
3. If an error occurs (and the worker is configured accordingly), handle_scheduling_exception comes in.
   This might re-enqueue the job or try a different model (which creates a new job).
"""


DEFAULT_RESOLUTION = timedelta(minutes=15)


def create_scheduling_job(
    sensor_id: int,
    start_of_schedule: datetime,
    end_of_schedule: datetime,
    belief_time: datetime,
    resolution: timedelta = DEFAULT_RESOLUTION,
    soc_at_start: Optional[float] = None,
    soc_targets: Optional[pd.Series] = None,
    soc_min: Optional[float] = None,
    soc_max: Optional[float] = None,
    roundtrip_efficiency: Optional[float] = None,
    consumption_price_sensor: Optional[Sensor] = None,
    production_price_sensor: Optional[Sensor] = None,
    inflexible_device_sensors: Optional[List[Sensor]] = None,
    job_id: Optional[str] = None,
    enqueue: bool = True,
) -> Job:
    """Supporting quick retrieval of the scheduling job, the job id is the unique entity address of the UDI event.
    That means one event leads to one job (i.e. actions are event driven).

    Target SOC values should be indexed by their due date. For example, for quarter-hourly targets between 5 and 6 AM:
    >>> df = pd.Series(data=[1, 2, 2.5, 3], index=pd.date_range(datetime(2010,1,1,5), datetime(2010,1,1,6), freq=timedelta(minutes=15), closed="right"))
    >>> print(df)
        2010-01-01 05:15:00    1.0
        2010-01-01 05:30:00    2.0
        2010-01-01 05:45:00    2.5
        2010-01-01 06:00:00    3.0
        Freq: 15T, dtype: float64
    """
    job = Job.create(
        make_schedule,
        kwargs=dict(
            sensor_id=sensor_id,
            start=start_of_schedule,
            end=end_of_schedule,
            belief_time=belief_time,
            resolution=resolution,
            soc_at_start=soc_at_start,
            soc_targets=soc_targets,
            soc_min=soc_min,
            soc_max=soc_max,
            roundtrip_efficiency=roundtrip_efficiency,
            consumption_price_sensor=consumption_price_sensor,
            production_price_sensor=production_price_sensor,
            inflexible_device_sensors=inflexible_device_sensors,
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
    )
    if enqueue:
        current_app.queues["scheduling"].enqueue_job(job)
    return job


def make_schedule(
    sensor_id: int,
    start: datetime,
    end: datetime,
    belief_time: datetime,
    resolution: timedelta,
    soc_at_start: Optional[float] = None,
    soc_targets: Optional[pd.Series] = None,
    soc_min: Optional[float] = None,
    soc_max: Optional[float] = None,
    roundtrip_efficiency: Optional[float] = None,
    consumption_price_sensor: Optional[Sensor] = None,
    production_price_sensor: Optional[Sensor] = None,
    inflexible_device_sensors: Optional[List[Sensor]] = None,
) -> bool:
    """Preferably, a starting soc is given.
    Otherwise, we try to retrieve the current state of charge from the asset (if that is the valid one at the start).
    Otherwise, we set the starting soc to 0 (some assets don't use the concept of a state of charge,
    and without soc targets and limits the starting soc doesn't matter).
    """
    # https://docs.sqlalchemy.org/en/13/faq/connections.html#how-do-i-use-engines-connections-sessions-with-python-multiprocessing-or-os-fork
    db.engine.dispose()

    rq_job = get_current_job()

    # find sensor
    sensor = Sensor.query.filter_by(id=sensor_id).one_or_none()

    if rq_job:
        click.echo(
            "Running Scheduling Job %s: %s, from %s to %s"
            % (rq_job.id, sensor, start, end)
        )

    if soc_at_start is None:
        if (
            start == sensor.get_attribute("soc_datetime")
            and sensor.get_attribute("soc_in_mwh") is not None
        ):
            soc_at_start = sensor.get_attribute("soc_in_mwh")
        else:
            soc_at_start = 0

    if soc_targets is None:
        soc_targets = initialize_series(
            data=np.nan, start=start, end=end, resolution=resolution, inclusive="right"
        )

    data_source_name = "Seita"

    # Choose which algorithm to use
    if "custom-scheduler" in sensor.attributes:
        scheduler_specs = sensor.attributes.get("custom-scheduler")
        scheduler, data_source_name = load_custom_scheduler(scheduler_specs)
        if rq_job:
            rq_job.meta["data_source_name"] = data_source_name
            rq_job.save_meta()
    elif sensor.generic_asset.generic_asset_type.name == "battery":
        scheduler = schedule_battery
    elif sensor.generic_asset.generic_asset_type.name in (
        "one-way_evse",
        "two-way_evse",
    ):
        scheduler = schedule_charging_station

    else:
        raise ValueError(
            "Scheduling is not (yet) supported for asset type %s."
            % sensor.generic_asset.generic_asset_type
        )

    consumption_schedule = scheduler(
        sensor,
        start,
        end,
        resolution,
        soc_at_start,
        soc_targets,
        soc_min,
        soc_max,
        roundtrip_efficiency,
        consumption_price_sensor=consumption_price_sensor,
        production_price_sensor=production_price_sensor,
        inflexible_device_sensors=inflexible_device_sensors,
        belief_time=belief_time,
    )

    data_source = get_data_source(
        data_source_name=data_source_name,
        data_source_type="scheduling script",
    )
    if rq_job:
        click.echo("Job %s made schedule." % rq_job.id)

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


def load_custom_scheduler(scheduler_specs: dict) -> Tuple[Callable, str]:
    """
    Read in custom scheduling spec.
    Attempt to load the Callable, also derive a data source name.

    Example specs:

    {
        "module": "/path/to/module.py",  # or sthg importable, e.g. "package.module"
        "function": "name_of_function",
        "source": "source name"
    }

    """
    assert isinstance(
        scheduler_specs, dict
    ), f"Scheduler specs is {type(scheduler_specs)}, should be a dict"
    assert "module" in scheduler_specs, "scheduler specs have no 'module'."
    assert "function" in scheduler_specs, "scheduler specs have no 'function'"

    source_name = scheduler_specs.get(
        "source", f"Custom scheduler - {scheduler_specs['function']}"
    )
    scheduler_name = scheduler_specs["function"]

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
        module, scheduler_specs["function"]
    ), "Module at {module_descr} has no function {scheduler_specs['function']}"

    return getattr(module, scheduler_specs["function"]), source_name


def handle_scheduling_exception(job, exc_type, exc_value, traceback):
    """
    Store exception as job meta data.
    """
    click.echo("HANDLING RQ WORKER EXCEPTION: %s:%s\n" % (exc_type, exc_value))
    job.meta["exception"] = exc_value
    job.save_meta()
