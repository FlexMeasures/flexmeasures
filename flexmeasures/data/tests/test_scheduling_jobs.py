# flake8: noqa: E402
from datetime import datetime, timedelta

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.tests.utils import work_on_rq, exception_reporter
from flexmeasures.data.services.scheduling import create_scheduling_job
from flexmeasures.utils.time_utils import as_server_time


def test_scheduling_a_battery(db, app, add_battery_assets, setup_test_data):
    """Test one clean run of one scheduling job:
    - data source was made,
    - schedule has been made
    """

    battery = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    start = as_server_time(datetime(2015, 1, 2))
    end = as_server_time(datetime(2015, 1, 3))
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
        Power.query.filter(Power.asset_id == battery.id)
        .filter(Power.data_source_id == scheduler_source.id)
        .all()
    )
    print([v.value for v in power_values])
    assert len(power_values) == 96
