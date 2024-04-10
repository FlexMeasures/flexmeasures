# flake8: noqa: E402
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from datetime import datetime, timedelta

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.job_cache import JobCache
from flexmeasures.data.services.forecasting import create_forecasting_jobs
from flexmeasures.utils.time_utils import as_server_time


def custom_model_params():
    """little training as we have little data, turn off transformations until they let this test run (TODO)"""
    return dict(
        training_and_testing_period=timedelta(hours=2),
        outcome_var_transformation=None,
        regressor_transformation={},
    )


def test_cache_on_create_forecasting_jobs(db, run_as_cli, app, setup_test_data):
    """Test we add job to cache on creating forecasting job + get job from cache"""
    wind_device_1: Sensor = setup_test_data["wind-asset-1"].sensors[0]

    job = create_forecasting_jobs(
        start_of_roll=as_server_time(datetime(2015, 1, 1, 6)),
        end_of_roll=as_server_time(datetime(2015, 1, 1, 7)),
        horizons=[timedelta(hours=1)],
        sensor_id=wind_device_1.id,
        custom_model_params=custom_model_params(),
    )

    assert app.job_cache.get(wind_device_1.id) == [job[0]]


class TestJobCache(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock(spec_set=["sadd", "smembers", "srem"])
        self.queues = {
            "forecasting": MagicMock(spec_set=["fetch_job"]),
            "scheduling": MagicMock(spec_set=["fetch_job"]),
        }
        self.job_cache = JobCache(self.connection, self.queues)
        self.job_cache.add("sensor_id", "job_id")

    def test_add(self):
        """Test adding to cache"""
        self.connection.sadd.assert_called_with("sensor_id", "job_id")

    def test_get_empty_queue(self):
        """Test getting from cache with empty queue"""
        self.queues["forecasting"].fetch_job.return_value = None
        self.queues["scheduling"].fetch_job.return_value = None
        self.connection.smembers.return_value = [b"job_id"]

        assert self.job_cache.get("sensor_id") == []
        assert self.connection.srem.call_count == 1

    def test_get_non_empty_forecasting_queue(self):
        """Test getting from cache with non empty forecasting queue"""
        forecasting_job = MagicMock()
        self.queues["forecasting"].fetch_job.return_value = forecasting_job
        self.queues["scheduling"].fetch_job.return_value = None
        self.connection.smembers.return_value = [b"job_id"]

        assert self.job_cache.get("sensor_id") == [forecasting_job]
        assert self.connection.srem.call_count == 0

    def test_get_non_empty_scheduling_queue(self):
        """Test getting from cache with non empty scheduling queue"""
        scheduling_job = MagicMock()
        self.queues["scheduling"].fetch_job.return_value = scheduling_job
        self.queues["forecasting"].fetch_job.return_value = None
        self.connection.smembers.return_value = [b"job_id"]

        assert self.job_cache.get("sensor_id") == [scheduling_job]
        assert self.connection.srem.call_count == 0
