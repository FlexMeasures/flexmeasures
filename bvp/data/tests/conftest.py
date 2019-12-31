import pytest
from datetime import datetime, timedelta
from random import random

import pandas as pd
import numpy as np
from flask_sqlalchemy import SQLAlchemy
from statsmodels.api import OLS

from bvp.data.models.data_sources import DataSource
from bvp.data.models.weather import WeatherSensorType, WeatherSensor, Weather
from bvp.data.models.assets import AssetType
from bvp.data.models.forecasting import model_map, ChainedModelSpecs
from bvp.utils.time_utils import as_bvp_time


@pytest.fixture(scope="function", autouse=True)
def setup_test_data(db, app, remove_seasonality_for_power_forecasts):
    """
    Adding a few forecasting jobs (based on data made in bvp.conftest).
    """
    print("Setting up data for data tests on %s" % db.engine)

    add_test_weather_sensor_and_forecasts(db)

    print("Done setting up data for data tests")


@pytest.fixture(scope="function", autouse=True)
def remove_seasonality_for_power_forecasts(db):
    """Make sure the AssetType specs make us query only data we actually have in the test db"""
    asset_types = AssetType.query.all()
    for a in asset_types:
        a.daily_seasonality = False
        a.weekly_seasonality = False
        a.yearly_seasonality = False


def add_test_weather_sensor_and_forecasts(db: SQLAlchemy):
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
            datetime(2015, 1, 1), datetime(2015, 1, 2, 23, 45), freq="15T"
        )
        values = [random() * (1 + np.sin(x / 15)) for x in range(len(time_slots))]
        if sensor_name == "temperature":
            values = [value * 17 for value in values]
        if sensor_name == "wind_speed":
            values = [value * 45 for value in values]
        if sensor_name == "radiation":
            values = [value * 600 for value in values]
        for dt, val in zip(time_slots, values):
            db.session.add(
                Weather(
                    sensor=sensor,
                    datetime=as_bvp_time(dt),
                    value=val,
                    horizon=timedelta(hours=6),
                    data_source_id=data_source.id,
                )
            )


@pytest.fixture(scope="function", autouse=True)
def add_failing_test_model(db):
    """Add a test model specs to the lookup which should fail due to missing data.
    It falls back to linear OLS (which falls back to naive)."""

    class TestSpecs(ChainedModelSpecs):
        def __init__(self, *args, **kwargs):
            model_identifier = "failing-test model (v1)"
            fallback_model_search_term = "Linear-OLS"
            model = OLS
            version = 1
            super().__init__(
                model_identifier=model_identifier,
                fallback_model_search_term=fallback_model_search_term,
                model=model,
                version=version,
                *args,
                **kwargs
            )
            self.start_of_training = self.start_of_training - timedelta(days=365)

    model_map["failing-test"] = TestSpecs
