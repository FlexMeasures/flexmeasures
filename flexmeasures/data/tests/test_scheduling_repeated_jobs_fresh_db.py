from __future__ import annotations

from datetime import datetime, timedelta

import pytz

from flexmeasures.data.tests.utils import work_on_rq, exception_reporter
from flexmeasures.data.services.scheduling import create_scheduling_job
from flexmeasures.data.models.planning import Scheduler
from flexmeasures.data.services.scheduling import load_custom_scheduler


class FailingScheduler(Scheduler):
    __author__ = "Test Organization"
    __version__ = "1"

    def compute(self):
        """
        This is a schedule that fails
        """

        raise Exception()

    def deserialize_config(self):
        """Do not care about any config sent in."""
        self.config_deserialized = True


def test_requeue_failing_job(
    fresh_db, app, add_charging_station_assets_fresh_db, setup_fresh_test_data
):
    """
    Testing that failing jobs are requeued.
    This test is called with a fresh db so that previous schedules don't interfere.
    """

    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2016, 1, 2))
    end = tz.localize(datetime(2016, 1, 3))
    resolution = timedelta(minutes=15)

    charging_station = add_charging_station_assets_fresh_db[
        "Test charging station"
    ].sensors[0]

    custom_scheduler = {
        "module": "flexmeasures.data.tests.test_scheduling_repeated_jobs_fresh_db",
        "class": "FailingScheduler",
    }

    # test if we can fetch the right scheduler class
    scheduler = load_custom_scheduler(custom_scheduler)(
        charging_station, start, end, resolution
    )
    assert isinstance(scheduler, FailingScheduler)

    # assigning scheduler to the sensor "Test charging station"
    charging_station.attributes["custom-scheduler"] = custom_scheduler

    # clean queue
    app.queues["scheduling"].empty()

    # calling the job twice, with the requeue argument to true
    jobs = []

    for _ in range(2):
        job = create_scheduling_job(
            asset_or_sensor=charging_station,
            start=start,
            end=end,
            resolution=resolution,
            enqueue=True,
            requeue=True,
        )

        work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)
        jobs.append(job)

    job1, job2 = jobs

    print(job1.failed_job_registry, len(job1.failed_job_registry))

    assert job1.id == job2.id  # equal job IDs
    assert job1.is_failed
    assert job2.is_failed

    print("JOB2: ", job2.enqueued_at)
    print("JOB1: ", job1.enqueued_at)

    # check if job2 has actually been requeued
    assert job1.enqueued_at < job2.enqueued_at
