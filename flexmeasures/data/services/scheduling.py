from datetime import datetime, timedelta
from typing import Optional

from flask import current_app
import click
import numpy as np
import pandas as pd
import pytz
from rq import get_current_job
from rq.job import Job
from sqlalchemy.exc import IntegrityError

from flexmeasures.data.config import db
from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.models.planning.battery import schedule_battery
from flexmeasures.data.models.planning.charging_station import schedule_charging_station
from flexmeasures.data.utils import save_to_session, get_data_source

"""
The life cycle of a scheduling job:
1. A scheduling job is born in create_scheduling_job.
2. It is run in make_schedule which writes results to the db.
3. If an error occurs (and the worker is configured accordingly), handle_scheduling_exception comes in.
   This might re-enqueue the job or try a different model (which creates a new job).
"""


DEFAULT_RESOLUTION = timedelta(minutes=15)


def create_scheduling_job(
    asset_id: int,
    start_of_schedule: datetime,
    end_of_schedule: datetime,
    belief_time: datetime,
    resolution: timedelta = DEFAULT_RESOLUTION,
    soc_at_start: Optional[float] = None,
    soc_targets: Optional[pd.Series] = None,
    udi_event_ea: Optional[str] = None,
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
            asset_id=asset_id,
            start=start_of_schedule,
            end=end_of_schedule,
            belief_time=belief_time,
            resolution=resolution,
            soc_at_start=soc_at_start,
            soc_targets=soc_targets,
        ),
        id=udi_event_ea,
        connection=current_app.queues["scheduling"].connection,
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
    asset_id: int,
    start: datetime,
    end: datetime,
    belief_time: datetime,
    resolution: timedelta,
    soc_at_start: Optional[float] = None,
    soc_targets: Optional[pd.Series] = None,
) -> bool:
    """Preferably, a starting soc is given.
    Otherwise, we try to retrieve the current state of charge from the asset (if that is the valid one at the start).
    Otherwise, we set the starting soc to 0 (some assets don't use the concept of a state of charge,
    and without soc targets and limits the starting soc doesn't matter).
    """
    # https://docs.sqlalchemy.org/en/13/faq/connections.html#how-do-i-use-engines-connections-sessions-with-python-multiprocessing-or-os-fork
    db.engine.dispose()

    rq_job = get_current_job()

    # find asset
    asset = Asset.query.filter_by(id=asset_id).one_or_none()

    click.echo(
        "Running Scheduling Job %s: %s, from %s to %s" % (rq_job.id, asset, start, end)
    )

    if soc_at_start is None:
        if start == asset.soc_datetime and asset.soc_in_mwh is not None:
            soc_at_start = asset.soc_in_mwh
        else:
            soc_at_start = 0

    if soc_targets is None:
        soc_targets = pd.Series(
            np.nan, index=pd.date_range(start, end, freq=resolution, closed="right")
        )

    if asset.asset_type_name == "battery":
        consumption_schedule = schedule_battery(
            asset, asset.market, start, end, resolution, soc_at_start, soc_targets
        )
    elif asset.asset_type_name in (
        "one-way_evse",
        "two-way_evse",
    ):
        consumption_schedule = schedule_charging_station(
            asset, asset.market, start, end, resolution, soc_at_start, soc_targets
        )
    else:
        raise ValueError(
            "Scheduling is not (yet) supported for asset type %s." % asset.asset_type
        )

    data_source = get_data_source(
        data_source_name="Seita",
        data_source_type="scheduling script",
    )
    click.echo("Job %s made schedule." % rq_job.id)

    ts_value_schedule = [
        Power(
            datetime=dt,
            horizon=dt.astimezone(pytz.utc) - belief_time.astimezone(pytz.utc),
            value=-value,
            asset_id=asset_id,
            data_source_id=data_source.id,
        )
        for dt, value in consumption_schedule.items()
    ]  # For consumption schedules, positive values denote consumption. For the db, consumption is negative

    try:
        save_to_session(ts_value_schedule)
    except IntegrityError as e:

        current_app.logger.warning(e)
        click.echo("Rolling back due to IntegrityError")
        db.session.rollback()

        if current_app.config.get("FLEXMEASURES_MODE", "") == "play":
            click.echo("Saving again, with overwrite=True")
            save_to_session(ts_value_schedule, overwrite=True)

    db.session.commit()

    return True


def handle_scheduling_exception(job, exc_type, exc_value, traceback):
    """
    Store exception as job meta data.
    """
    click.echo("HANDLING RQ WORKER EXCEPTION: %s:%s\n" % (exc_type, exc_value))
    job.meta["exception"] = exc_value
    job.save_meta()
