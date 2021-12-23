from datetime import timedelta, datetime

import numpy as np
import pandas as pd

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.services.scheduling import create_scheduling_job
from flexmeasures.data.tests.utils import work_on_rq, exception_reporter
from flexmeasures.utils.time_utils import as_server_time


def test_scheduling_a_charging_station(
    db, app, add_charging_station_assets, setup_test_data
):
    """Test one clean run of one scheduling job:
    - data source was made,
    - schedule has been made

    Starting with a state of charge 1 kWh, within 2 hours we should be able to reach 5 kWh.
    """
    soc_at_start = 1
    target_soc = 5
    duration_until_target = timedelta(hours=2)

    charging_station = Sensor.query.filter(
        Sensor.name == "Test charging station"
    ).one_or_none()
    start = as_server_time(datetime(2015, 1, 2))
    end = as_server_time(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    target_soc_datetime = start + duration_until_target
    soc_targets = pd.Series(
        np.nan, index=pd.date_range(start, end, freq=resolution, closed="right")
    )
    soc_targets.loc[target_soc_datetime] = target_soc

    assert (
        DataSource.query.filter_by(name="Seita", type="scheduling script").one_or_none()
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

    scheduler_source = DataSource.query.filter_by(
        name="Seita", type="scheduling script"
    ).one_or_none()
    assert (
        scheduler_source is not None
    )  # Make sure the scheduler data source is now there

    power_values = (
        TimedBelief.query.filter(TimedBelief.sensor_id == charging_station.id)
        .filter(TimedBelief.source_id == scheduler_source.id)
        .all()
    )
    consumption_schedule = pd.Series(
        [-v.event_value for v in power_values],
        index=pd.DatetimeIndex([v.event_start for v in power_values]),
    )  # For consumption schedules, positive values denote consumption. For the db, consumption is negative
    assert len(consumption_schedule) == 96
    print(consumption_schedule.head(12))
    assert (
        consumption_schedule.head(8).sum() * (resolution / timedelta(hours=1)) == 4.0
    )  # The first 2 hours should consume 4 kWh to charge from 1 to 5 kWh
