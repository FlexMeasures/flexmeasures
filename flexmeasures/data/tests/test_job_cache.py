# flake8: noqa: E402
from __future__ import annotations

import pytest
import pytz
import unittest

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from redis.exceptions import ConnectionError
from rq.job import NoSuchJobError

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.forecasting.pipelines import TrainPredictPipeline
from flexmeasures.data.services.job_cache import JobCache, NoRedisConfigured
from flexmeasures.data.services.scheduling import create_scheduling_job
from flexmeasures.utils.time_utils import as_server_time


def test_cache_on_create_forecasting_jobs(db, run_as_cli, app, setup_test_data):
    """Test we add job to cache on creating forecasting job + get job from cache"""
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

    assert app.job_cache.get(wind_device_1.id, "forecasting", "sensor") == [job]


def test_cache_on_create_scheduling_jobs(db, app, add_battery_assets, setup_test_data):
    """Test we add job to cache on creating scheduling job + get job from cache"""
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

    assert app.job_cache.get(battery.id, "scheduling", "sensor") == [job]


class TestJobCache(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock(spec_set=["sadd", "smembers", "srem", "ping"])
        self.job_cache = JobCache(self.connection)
        self.cache_key = "forecasting:sensor:sensor_id"
        self.mock_redis_job = MagicMock(spec_set=["fetch"])

    def test_no_redis_configured(self):
        """Test raising NoRedisConfigured"""
        self.connection.ping.side_effect = ConnectionError
        with pytest.raises(NoRedisConfigured):
            self.job_cache.add(
                "sensor_id",
                "job_id",
                queue="forecasting",
                asset_or_sensor_type="sensor",
            )
        self.connection.sadd.assert_not_called()

        with pytest.raises(NoRedisConfigured):
            self.job_cache.get("sensor_id", "forecasting", "sensor")
        self.connection.smembers.assert_not_called()

    def test_add(self):
        """Test adding to cache"""
        self.job_cache.add(
            "sensor_id", "job_id", queue="forecasting", asset_or_sensor_type="sensor"
        )
        self.connection.sadd.assert_called_with(self.cache_key, "job_id")

    def test_get_empty_queue(self):
        """Test getting from cache with empty queue"""
        self.job_cache.add(
            "sensor_id", "job_id", queue="forecasting", asset_or_sensor_type="sensor"
        )
        self.connection.smembers.return_value = [b"job_id"]

        self.mock_redis_job.fetch.side_effect = NoSuchJobError
        with patch("flexmeasures.data.services.job_cache.Job", new=self.mock_redis_job):
            assert self.job_cache.get("sensor_id", "forecasting", "sensor") == []
            assert self.connection.srem.call_count == 1

    def test_get_non_empty_queue(self):
        """Test getting from cache with non empty forecasting queue"""
        self.job_cache.add(
            "sensor_id", "job_id", queue="forecasting", asset_or_sensor_type="sensor"
        )
        forecasting_job = MagicMock()
        self.connection.smembers.return_value = [b"job_id"]

        self.mock_redis_job.fetch.return_value = forecasting_job
        with patch("flexmeasures.data.services.job_cache.Job", new=self.mock_redis_job):
            assert self.job_cache.get("sensor_id", "forecasting", "sensor") == [
                forecasting_job
            ]
            assert self.connection.srem.call_count == 0
