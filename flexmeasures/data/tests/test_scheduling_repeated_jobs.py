from __future__ import annotations

from datetime import datetime, timedelta
import copy
import logging
import threading
import time

import pytz
import pytest
from rq.job import Job, JobStatus
from sqlalchemy import select

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.tests.utils import exception_reporter
from flexmeasures.utils.job_utils import work_on_rq
from flexmeasures.data.services.scheduling import create_scheduling_job
from flexmeasures.data.services.utils import hash_function_arguments, job_cache


@pytest.mark.parametrize(
    "args_modified, kwargs_modified, equal",
    [
        (
            [1, 2, "1"],
            {
                "key1": "value1",
                "key2": "value2",
                "key3": 3,
                "key4": {"key1_nested": 1, "key2_nested": 2},
                "key5": '{"serialized_key1_nested": 1, "serialized_key2_nested": 2}',
            },
            True,
        ),
        (
            [1, 2, "1"],
            {
                "key1": "value1",
                "key2": "value2",
                "key3": 3,
                "key4": {"key2_nested": 2, "key1_nested": 1},
                "key5": '{"serialized_key1_nested": 1, "serialized_key2_nested": 2}',
            },
            True,
        ),
        (
            [1, 2, 1],
            {
                "key1": "value1",
                "key2": "value2",
                "key3": 3,
                "key4": {"key1_nested": 1, "key2_nested": 2},
                "key5": '{"serialized_key1_nested": 1, "serialized_key2_nested": 2}',
            },
            False,
        ),
        (
            [1, 2, "1"],
            {
                "key1": "different",
                "key2": "value2",
                "key3": 3,
                "key4": {"key1_nested": 1, "key2_nested": 2},
                "key5": '{"serialized_key1_nested": 1, "serialized_key2_nested": 2}',
            },
            False,
        ),
        (
            [1, 2, "1"],
            {
                "different": "value1",
                "key2": "value2",
                "key3": 3,
                "key4": {"key1_nested": 1, "key2_nested": 2},
                "key5": '{"serialized_key1_nested": 1, "serialized_key2_nested": 2}',
            },
            False,
        ),
        (
            ["1", 1, 2],
            {
                "key1": "value1",
                "key2": "value2",
                "key3": 3,
                "key4": {"key1_nested": 1, "key2_nested": 2},
                "key5": '{"serialized_key1_nested": 1, "serialized_key2_nested": 2}',
            },
            False,
        ),
        (
            [1, 2, "1"],
            {
                "key1": "value1",
                "key2": "value2",
                "key3": 3,
                "key4": {"key1_nested": "different", "key2_nested": 2},
                "key5": '{"serialized_key1_nested": 1, "serialized_key2_nested": 2}',
            },
            False,
        ),
        (
            [1, 2, "1"],
            {
                "key1": "value1",
                "key2": "value2",
                "key3": 3,
                "key4": {"key1_nested": 1, "key2_nested": 2},
                "key5": '{"serialized_key2_nested": 2, "serialized_key1_nested": 1}',
            },
            False,
        ),
    ],
)
def test_hashing_simple(args_modified: list, kwargs_modified: dict, equal: bool):
    args = [1, 2, "1"]
    kwargs = {
        "key1": "value1",
        "key2": "value2",
        "key3": 3,
        "key4": {"key1_nested": 1, "key2_nested": 2},
        "key5": '{"serialized_key1_nested": 1, "serialized_key2_nested": 2}',
    }

    hash_original = hash_function_arguments(args, kwargs)
    hash_modified = hash_function_arguments(args_modified, kwargs_modified)

    if equal:
        assert hash_original == hash_modified
    else:
        assert hash_original != hash_modified


def test_hashing(db, app, add_charging_station_assets, setup_test_data):
    soc_at_start = 1
    target_soc = 5
    duration_until_target = timedelta(hours=2)

    # Here, we need to obtain the object through a db query, otherwise we run into session issues with deepcopy later on
    # charging_station = add_charging_station_assets["Test charging station"].sensors[0]
    charging_station = db.session.execute(
        select(Sensor)
        .filter(Sensor.name == "power")
        .join(GenericAsset, Sensor.generic_asset_id == GenericAsset.id)
        .filter(GenericAsset.id == Sensor.generic_asset_id)
        .filter(GenericAsset.name == "Test charging stations")
    ).scalar_one_or_none()
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    target_datetime = start + duration_until_target
    resolution = timedelta(minutes=15)
    soc_targets = [dict(datetime=target_datetime.isoformat(), value=target_soc)]

    kwargs = dict(
        sensor=charging_station,
        start=start,
        end=end,
        belief_time=start,
        resolution=resolution,
        flex_model={"soc-at-start": soc_at_start, "soc-targets": soc_targets},
    )
    args = []

    hash = hash_function_arguments(args, kwargs)
    print("RIGHT HASH: ", hash)

    # checks that hashes are consistent between different runtime calls
    # this test needs to be updated in case of a version upgrade
    assert hash == "oAZ8tzzq50zl3I+7oFeabrj1QeH709mZdXWbpkn0krA="

    kwargs2 = copy.deepcopy(kwargs)
    args2 = copy.deepcopy(args)

    # checks that hashes are consistent within the same runtime calls
    hash2 = hash_function_arguments(args2, kwargs2)
    assert hash2 == hash

    # checks that different arguments yield different hashes
    kwargs2["resolution"] = timedelta(minutes=12)
    hash3 = hash_function_arguments(args2, kwargs2)
    assert hash != hash3


def test_scheduling_multiple_triggers(
    caplog, db, app, add_charging_station_assets, setup_test_data
):
    caplog.set_level(
        logging.INFO
    )  # setting the logging level of the log capture fixture

    duration_until_target = timedelta(hours=2)

    charging_station = add_charging_station_assets["Test charging station"].sensors[0]
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    target_datetime = start + duration_until_target
    soc_start = 2.5

    assert (
        db.session.execute(
            select(DataSource).filter_by(name="FlexMeasures", type="scheduling script")
        ).scalar_one_or_none()
        is None
    )  # Make sure the scheduler data source isn't there

    # clear logs
    caplog.clear()

    jobs = []

    # create jobs
    for target_soc in [1, 1, 4]:
        soc_targets = [dict(datetime=target_datetime.isoformat(), value=target_soc)]

        job = create_scheduling_job(
            asset_or_sensor=charging_station,
            start=start,
            end=end,
            belief_time=start,
            resolution=resolution,
            flex_model={"soc-at-start": soc_start, "soc-targets": soc_targets},
            enqueue=False,
        )

        # enqueue & run job
        app.queues["scheduling"].enqueue_job(job)
        jobs.append(job)

    work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)

    job1, job2, job3 = jobs

    print(job1.id, job2.id, job3.id)

    # checking that jobs 1 & 2 they have the same job id
    assert job1.id == job2.id

    # checking that job3 has different id
    assert job3.id != job1.id


def failing_function(*args, **kwargs):
    raise Exception()


def test_allow_trigger_failed_jobs(
    caplog, db, app, add_charging_station_assets, setup_test_data
):
    @job_cache("scheduling")
    def create_failing_job(
        arg1: int,
        kwarg1: int | None = None,
        kwarg2: int | None = None,
    ) -> Job:
        """
        This function creates and enqueues a failing job.
        """

        job = Job.create(
            failing_function,
            kwargs=dict(kwarg1=kwarg1, kwarg2=kwarg2),
            connection=app.queues["scheduling"].connection,
        )

        app.queues["scheduling"].enqueue_job(job)

        return job

    job1 = create_failing_job(1, 1, 1)  # this job will fail when worked on
    work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)

    assert job1.get_status() == JobStatus.FAILED  # check that the job fails

    job2 = create_failing_job(1, 1, 1)
    work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)

    assert job1.id == job2.id


def successful_function(*args, **kwargs):
    pass


def test_force_new_job_creation(db, app, add_charging_station_assets, setup_test_data):
    @job_cache("scheduling")
    def create_successful_job(
        arg1: int,
        kwarg1: int | None = None,
        kwarg2: int | None = None,
        force_new_job_creation=False,
    ) -> Job:
        """
        This function creates and enqueues a successful job.
        """

        job = Job.create(
            successful_function,
            kwargs=dict(kwarg1=kwarg1, kwarg2=kwarg2),
            connection=app.queues["scheduling"].connection,
        )

        app.queues["scheduling"].enqueue_job(job)

        return job

    job1 = create_successful_job(1, 1, 1, force_new_job_creation=True)
    work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)

    job2 = create_successful_job(1, 1, 1, force_new_job_creation=False)
    work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)

    # check that `force_new_job_creation` doesn't affect the hash
    assert job1.id == job2.id  # caching job

    job3 = create_successful_job(1, 1, 1, force_new_job_creation=True)
    work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)

    # check that `force_new_job_creation=True` actually triggers a new job creation
    assert job2.id != job3.id


def test_concurrent_identical_calls_share_one_job(db, app):
    """Concurrent calls with the same arguments must share one job, rather than each creating their own.

    Without a lock, both calls miss the cache before either one stores its job,
    which let two identical scheduling requests create two data sources for one schedule (#2611).
    """
    both_called = threading.Barrier(2)

    @job_cache("scheduling")
    def create_slow_job(arg1: int, kwarg1: int | None = None) -> Job:
        # widen the window between checking the cache and storing the new job in it
        time.sleep(0.2)
        job = Job.create(
            successful_function,
            kwargs=dict(kwarg1=kwarg1),
            connection=app.queues["scheduling"].connection,
        )
        app.queues["scheduling"].enqueue_job(job)
        return job

    jobs = []

    def call():
        with app.app_context():
            both_called.wait()
            jobs.append(create_slow_job(1, kwarg1=1))

    threads = [threading.Thread(target=call) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(jobs) == 2
        assert jobs[0].id == jobs[1].id
    finally:
        # keep the enqueued job(s) from leaking into later tests
        app.queues["scheduling"].empty()
