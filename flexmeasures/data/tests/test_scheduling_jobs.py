# flake8: noqa: E402
from typing import Callable
from datetime import datetime, timedelta
import os
import pytz

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.tests.utils import work_on_rq, exception_reporter
from flexmeasures.data.services.scheduling import create_scheduling_job, load_custom_scheduler


def test_scheduling_a_battery(db, app, add_battery_assets, setup_test_data):
    """Test one clean run of one scheduling job:
    - data source was made,
    - schedule has been made
    """

    battery = Sensor.query.filter(Sensor.name == "Test battery").one_or_none()
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)

    assert (
        DataSource.query.filter_by(name="Seita", type="scheduling script").one_or_none()
        is None
    )  # Make sure the scheduler data source isn't there

    job = create_scheduling_job(
        battery.id, start, end, belief_time=start, resolution=resolution
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
        TimedBelief.query.filter(TimedBelief.sensor_id == battery.id)
        .filter(TimedBelief.source_id == scheduler_source.id)
        .all()
    )
    print([v.event_value for v in power_values])
    assert len(power_values) == 96


def test_loading_custom_schedule():
    """
    Simply check if loading a custom scheduler works.
    """
    path_to_here = os.path.dirname(__file__)
    scheduler_specs = {
        "path": os.path.join(path_to_here, "dummy_scheduler.py"),
        "function": "compute_a_schedule",
        "source": "Test Source"
    }
    custom_scheduler, data_source = load_custom_scheduler(scheduler_specs)
    assert data_source == "Test Source"
    assert custom_scheduler.__name__ == "compute_a_schedule"
    assert custom_scheduler.__doc__ == "Just a test scheduler."