# flake8: noqa: E402
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from bvp.data.models.data_sources import DataSource
from bvp.data.models.assets import Asset, Power
from bvp.data.tests.utils import work_on_rq, exception_reporter
from bvp.data.services.scheduling import create_scheduling_job
from bvp.utils.time_utils import as_bvp_time


def test_scheduling_a_battery(db, app):
    """Test one clean run of one scheduling job:
    - data source was made,
    - schedule has been made
    """

    battery = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    start = as_bvp_time(datetime(2015, 1, 2))
    end = as_bvp_time(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)

    assert (
        DataSource.query.filter(DataSource.label == "schedule by Seita").one_or_none()
        is None
    )  # Make sure the scheduler data source isn't there

    job = create_scheduling_job(
        battery.id, start, end, belief_time=start, resolution=resolution
    )

    print("Job: %s" % job.id)

    work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)

    scheduler_source = DataSource.query.filter(
        DataSource.label == "schedule by Seita"
    ).one_or_none()
    assert (
        scheduler_source is not None
    )  # Make sure the scheduler data source is now there

    schedule = (
        Power.query.filter(Power.asset_id == battery.id)
        .filter(Power.data_source_id == scheduler_source.id)
        .all()
    )
    print([v.value for v in schedule])
    assert len(schedule) == 96


def test_scheduling_a_charging_station(db, app):
    """Test one clean run of one scheduling job:
    - data source was made,
    - schedule has been made

    Starting with a state of charge 1 kWh, within 2 hours we should be able to reach 5 kWh.
    """
    soc_at_start = 1
    target_soc = 5
    duration_until_target = timedelta(hours=2)

    charging_station = Asset.query.filter(
        Asset.name == "Test charging station"
    ).one_or_none()
    start = as_bvp_time(datetime(2015, 1, 2))
    end = as_bvp_time(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    target_soc_datetime = start + duration_until_target
    soc_targets = pd.Series(
        np.nan, index=pd.date_range(start, end, freq=resolution, closed="right")
    )
    soc_targets.loc[target_soc_datetime] = target_soc

    assert (
        DataSource.query.filter(DataSource.label == "schedule by Seita").one_or_none()
        is None
    )  # Make sure the scheduler data source isn't there

    job = create_scheduling_job(
        charging_station.id,
        start,
        end,
        belief_time=start,
        resolution=resolution,
        soc_at_start=soc_at_start,
        soc_targets=soc_targets,
    )

    print("Job: %s" % job.id)

    work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)

    scheduler_source = DataSource.query.filter(
        DataSource.label == "schedule by Seita"
    ).one_or_none()
    assert (
        scheduler_source is not None
    )  # Make sure the scheduler data source is now there

    schedule = (
        Power.query.filter(Power.asset_id == charging_station.id)
        .filter(Power.data_source_id == scheduler_source.id)
        .all()
    )
    schedule = pd.Series(
        [v.value for v in schedule],
        index=pd.DatetimeIndex([v.datetime for v in schedule]),
    )
    assert len(schedule) == 96
    print(schedule.head(12))
    assert (
        schedule.head(8).sum() * (resolution / timedelta(hours=1)) == 4.0
    )  # The first 2 hours should consume 4 kWh to charge from 1 to 5 kWh
