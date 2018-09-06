import pytest
from datetime import datetime, timedelta
from random import random

import pandas as pd
import numpy as np
from flask_sqlalchemy import SQLAlchemy

from bvp.data.models.data_sources import DataSource
from bvp.data.models.weather import WeatherSensorType, WeatherSensor, Weather
from bvp.data.models.assets import Asset
from bvp.data.models.forecasting.jobs import ForecastingJob
from bvp.utils.time_utils import as_bvp_time


@pytest.fixture(scope="function", autouse=True)
def setup_test_data(db):
    """
    Adding a few forecasting jobs (based on data made in bvp.conftest).
    """
    print("Setting up data for data tests on %s" % db.engine)

    add_weather_sensor_and_forecasts(db)
    add_forecasting_jobs(db)

    print("Done setting up data for data tests")


def add_weather_sensor_and_forecasts(db: SQLAlchemy):
    """one day of test data (one complete sine curve) for two sensors"""
    data_source = DataSource.query.filter_by(
        label="data entered for demonstration purposes", type="script"
    ).one_or_none()
    for sensor_name in ("radiation", "wind_speed"):
        sensor_type = WeatherSensorType(name=sensor_name)
        sensor = WeatherSensor(
            name=sensor_name, sensor_type=sensor_type, latitude=100, longitude=100
        )
        db.session.add(sensor)
        time_slots = pd.date_range(
            datetime(2015, 1, 1), datetime(2015, 1, 1, 23, 45), freq="15T"
        )
        values = [random() * (1 + np.sin(x / 15)) for x in range(len(time_slots))]
        if sensor_name == "temperature":
            values = values * 17
        if sensor_name == "wind_speed":
            values = values * 45
        for dt, val in zip(time_slots, values):
            db.session.add(
                Weather(
                    sensor=sensor,
                    datetime=as_bvp_time(dt),
                    value=val,
                    horizon=timedelta(minutes=15),
                    data_source_id=data_source.id,
                )
            )


def add_forecasting_jobs(db: SQLAlchemy):
    wind_device_1 = Asset.query.filter_by(name="wind-asset-1").one_or_none()
    wind_device_2 = Asset.query.filter_by(name="wind-asset-2").one_or_none()
    solar_device_1 = Asset.query.filter_by(name="solar-asset-1").one_or_none()
    db.session.add(
        ForecastingJob(
            start=as_bvp_time(datetime(2015, 1, 1, 6)),
            end=as_bvp_time(datetime(2015, 1, 1, 7)),
            horizon=timedelta(minutes=15),
            timed_value_type="Power",
            asset_id=wind_device_1.id,
        )
    )
    db.session.add(
        ForecastingJob(
            start=as_bvp_time(datetime(2015, 1, 1, 14)),
            end=as_bvp_time(datetime(2015, 1, 1, 17)),
            horizon=timedelta(minutes=15),
            timed_value_type="Power",
            asset_id=wind_device_2.id,
        )
    )
    db.session.add(
        ForecastingJob(
            start=as_bvp_time(datetime(2015, 1, 1, 20)),
            end=as_bvp_time(datetime(2015, 1, 1, 22)),
            horizon=timedelta(minutes=15),
            timed_value_type="Power",
            asset_id=solar_device_1.id,
        )
    )
    # This one should fail as there is no underlying data - and due to the start date it is the last to be picked.
    db.session.add(
        ForecastingJob(
            start=as_bvp_time(datetime(2016, 1, 1, 20)),
            end=as_bvp_time(datetime(2016, 1, 1, 22)),
            horizon=timedelta(minutes=15),
            timed_value_type="Power",
            asset_id=solar_device_1.id,
        )
    )
