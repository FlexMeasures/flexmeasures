# flake8: noqa: E402
from __future__ import annotations

import pytest
import pytz
import unittest

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from redis.exceptions import ConnectionError

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.forecasting.pipelines import TrainPredictPipeline
from flexmeasures.data.services.job_map import JobMap, NoRedisConfigured
from rq.job import Job
from flexmeasures.data.services.scheduling import create_scheduling_job
from flexmeasures.tests.utils import RQCompatibleFakeStrictRedis
from flexmeasures.utils.time_utils import as_server_time


def test_index_forecasting_jobs_on_creation(db, run_as_cli, app, setup_test_data):
    """Forecasting jobs are indexed by sensor when they are created."""
    wind_device_1: Sensor = setup_test_data["wind-asset-1"].sensors[0]

    pipeline = TrainPredictPipeline(
        config={
            "train-start": "2015-01-01T00:00:00+00:00",
            "retrain-frequency": "PT1H",
        }
    )
    pipeline_returns = pipeline.compute(
        as_job=True,
        parameters={
            "sensor": wind_device_1.id,
            "start": as_server_time(datetime(2015, 1, 1, 6)).isoformat(),
            "end": as_server_time(datetime(2015, 1, 1, 7)).isoformat(),
            "max-forecast-horizon": "PT1H",
            "forecast-frequency": "PT1H",
        },
    )
    job = app.queues["forecasting"].fetch_job(pipeline_returns["job_id"])

    assert app.job_map.get(wind_device_1.id, "forecasting", "sensor") == [job]


def test_index_scheduling_jobs_on_creation(
    db, app, add_battery_assets, setup_test_data
):
    """Scheduling jobs are indexed by sensor when they are created."""
    battery = add_battery_assets["Test battery"].sensors[0]
    tz = pytz.timezone("Europe/Amsterdam")
    start, end = tz.localize(datetime(2015, 1, 2)), tz.localize(datetime(2015, 1, 3))

    job = create_scheduling_job(
        asset_or_sensor=battery,
        start=start,
        end=end,
        belief_time=start,
        resolution=timedelta(minutes=15),
    )

    assert app.job_map.get(battery.id, "scheduling", "sensor") == [job]


def test_legacy_app_job_cache_alias(app):
    """External plugins can still register jobs through the old app attribute."""
    assert app.job_cache is app.job_map


def test_get_enqueued_at_and_fetch_jobs(app, clean_redis):
    """Paging reads only enqueue times, prunes expired jobs, and then fetches just the jobs it needs."""
    queue = app.queues["scheduling"]
    enqueued_job = queue.enqueue(sum, [1, 2])
    waiting_job = queue.enqueue(sum, [3, 4], depends_on=enqueued_job)
    for job_id in (enqueued_job.id, waiting_job.id, "expired-job"):
        app.job_map.add(1, job_id, queue="scheduling", asset_or_sensor_type="asset")

    enqueued_ats = dict(app.job_map.get_enqueued_at(1, "scheduling", "asset"))

    # A job waiting on another one was created but not enqueued yet, so it is listed without an enqueue time.
    assert enqueued_ats == {
        enqueued_job.id: enqueued_job.enqueued_at,
        waiting_job.id: None,
    }
    assert enqueued_ats[enqueued_job.id].tzinfo is not None
    # The job without a hash in Redis is removed from the index.
    assert app.job_map.connection.smembers("scheduling:asset:1") == {
        enqueued_job.id.encode(),
        waiting_job.id.encode(),
    }

    fetched = app.job_map.fetch_jobs([waiting_job.id, "expired-job", enqueued_job.id])
    assert [job.id if job else None for job in fetched] == [
        waiting_job.id,
        None,
        enqueued_job.id,
    ]

    queue.empty()


class TestJobMap(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock(spec_set=["sadd", "smembers", "srem", "ping"])
        self.job_map = JobMap(self.connection)
        self.index_key = "forecasting:sensor:sensor_id"
        self.mock_redis_job = MagicMock(spec_set=["fetch_many"])

    def test_no_redis_configured(self):
        """Test raising NoRedisConfigured"""
        self.connection.ping.side_effect = ConnectionError
        with pytest.raises(NoRedisConfigured):
            self.job_map.add(
                "sensor_id",
                "job_id",
                queue="forecasting",
                asset_or_sensor_type="sensor",
            )
        self.connection.sadd.assert_not_called()

        with pytest.raises(NoRedisConfigured):
            self.job_map.get("sensor_id", "forecasting", "sensor")
        self.connection.smembers.assert_not_called()

    def test_add(self):
        """Test adding a job ID to the Redis index."""
        self.job_map.add(
            "sensor_id", "job_id", queue="forecasting", asset_or_sensor_type="sensor"
        )
        self.connection.sadd.assert_called_with(self.index_key, "job_id")


@pytest.fixture
def fake_redis():
    return RQCompatibleFakeStrictRedis()


def _saved_job(connection) -> Job:
    job = Job.create("flexmeasures.utils.time_utils.server_now", connection=connection)
    job.save()
    return job


def test_get_drops_expired_jobs(fake_redis):
    """Jobs that expired from Redis are left out, and their IDs are removed from the index."""
    job_map = JobMap(fake_redis)
    kept, expired = _saved_job(fake_redis), _saved_job(fake_redis)
    for job in (kept, expired):
        job_map.add("sensor_id", job.id, "forecasting", "sensor")
    expired.delete()

    assert job_map.get("sensor_id", "forecasting", "sensor") == [kept]
    assert fake_redis.smembers("forecasting:sensor:sensor_id") == {kept.id.encode()}


def test_get_many_takes_a_fixed_number_of_round_trips(fake_redis):
    """Reading several entries costs a ping and a few pipelines, however many entries and jobs there are.

    Commands sent in a pipeline share one round trip, so only direct commands and pipelines are counted.
    """
    job_map = JobMap(fake_redis)
    entries = [(sensor_id, "scheduling", "sensor") for sensor_id in (1, 2, 3)]
    jobs = {entry: [_saved_job(fake_redis) for _ in range(4)] for entry in entries}
    # A job indexed under two entries is returned under both.
    shared = _saved_job(fake_redis)
    jobs[entries[0]].append(shared)
    jobs[entries[1]].append(shared)
    for entry, entry_jobs in jobs.items():
        for job in entry_jobs:
            job_map.add(entry[0], job.id, entry[1], entry[2])
    expired = _saved_job(fake_redis)
    job_map.add(3, expired.id, "scheduling", "sensor")
    expired.delete()

    with (
        patch.object(
            fake_redis, "execute_command", wraps=fake_redis.execute_command
        ) as direct_commands,
        patch.object(fake_redis, "pipeline", wraps=fake_redis.pipeline) as pipelines,
    ):
        result = job_map.get_many(entries)

    assert {entry: set(entry_jobs) for entry, entry_jobs in result.items()} == {
        entry: set(entry_jobs) for entry, entry_jobs in jobs.items()
    }
    # One ping, then one pipeline each to read the job IDs, read the jobs and remove the expired ID.
    assert direct_commands.call_count == 1
    assert pipelines.call_count == 3
    assert expired.id.encode() not in fake_redis.smembers("scheduling:sensor:3")
