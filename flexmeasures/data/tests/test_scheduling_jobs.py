# flake8: noqa: E402
from datetime import datetime, timedelta
import os

import pytz
import pytest
from rq.job import Job

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.tests.utils import work_on_rq, exception_reporter
from flexmeasures.data.services.scheduling import (
    create_scheduling_job,
    load_custom_scheduler,
)


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
        DataSource.query.filter_by(
            name="FlexMeasures", type="scheduling script"
        ).one_or_none()
        is None
    )  # Make sure the scheduler data source isn't there

    job = create_scheduling_job(
        sensor=battery,
        start=start,
        end=end,
        belief_time=start,
        resolution=resolution,
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


scheduler_specs = {
    "module": None,  # use make_module_descr, see below
    "class": "DummyScheduler",
}


def make_module_descr(is_path):
    if is_path:
        path_to_here = os.path.dirname(__file__)
        return os.path.join(path_to_here, "dummy_scheduler.py")
    else:
        return "flexmeasures.data.tests.dummy_scheduler"


@pytest.mark.parametrize("is_path", [False, True])
def test_loading_custom_scheduler(is_path: bool):
    """
    Simply check if loading a custom scheduler works.
    """
    scheduler_specs["module"] = make_module_descr(is_path)
    custom_scheduler = load_custom_scheduler(scheduler_specs)
    assert custom_scheduler.__name__ == "DummyScheduler"
    assert "Just a dummy scheduler" in custom_scheduler.compute_schedule.__doc__

    data_source_info = custom_scheduler.get_data_source_info()
    assert data_source_info["name"] == "Test Organization"
    assert data_source_info["version"] == "3"
    assert data_source_info["model"] == "DummyScheduler"


@pytest.mark.parametrize("is_path", [False, True])
def test_assigning_custom_scheduler(db, app, add_battery_assets, is_path: bool):
    """
    Test if the custom scheduler is picked up when we assign it to a Sensor,
    and that its dummy values are saved.
    """
    scheduler_specs["module"] = make_module_descr(is_path)

    battery = Sensor.query.filter(Sensor.name == "Test battery").one_or_none()
    battery.attributes["custom-scheduler"] = scheduler_specs

    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)

    job = create_scheduling_job(
        sensor=battery,
        start=start,
        end=end,
        belief_time=start,
        resolution=resolution,
    )
    print("Job: %s" % job.id)

    work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)

    # make sure we saved the data source for later lookup
    redis_connection = app.queues["scheduling"].connection
    finished_job = Job.fetch(job.id, connection=redis_connection)
    assert finished_job.meta["data_source_info"]["model"] == scheduler_specs["class"]

    scheduler_source = DataSource.query.filter_by(
        type="scheduling script",
        **finished_job.meta["data_source_info"],
    ).one_or_none()
    assert (
        scheduler_source is not None
    )  # Make sure the scheduler data source is now there

    power_values = (
        TimedBelief.query.filter(TimedBelief.sensor_id == battery.id)
        .filter(TimedBelief.source_id == scheduler_source.id)
        .all()
    )
    assert len(power_values) == 96
    # test for negative value as we schedule consumption
    assert all(
        [
            v.event_value == -1 * battery.get_attribute("capacity_in_mw")
            for v in power_values
        ]
    )
