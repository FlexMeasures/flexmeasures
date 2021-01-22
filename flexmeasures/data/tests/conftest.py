import pytest
from datetime import datetime, timedelta
from random import random

import pandas as pd
import numpy as np
from flask_sqlalchemy import SQLAlchemy
from statsmodels.api import OLS

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.weather import WeatherSensorType, WeatherSensor, Weather
from flexmeasures.data.models.assets import AssetType
from flexmeasures.data.models.forecasting import model_map
from flexmeasures.data.models.forecasting.model_spec_factory import (
    create_initial_model_specs,
)
from flexmeasures.utils.time_utils import as_server_time


@pytest.fixture(scope="function", autouse=True)
def setup_test_data(db, app, remove_seasonality_for_power_forecasts):
    """
    Adding a few forecasting jobs (based on data made in flexmeasures.conftest).
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
        name="Seita", type="demo script"
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
                    datetime=as_server_time(dt),
                    value=val,
                    horizon=timedelta(hours=6),
                    data_source_id=data_source.id,
                )
            )


@pytest.fixture(scope="function", autouse=True)
def add_failing_test_model(db):
    """Add a test model specs to the lookup which should fail due to missing data.
    It falls back to linear OLS (which falls back to naive)."""

    def test_specs(**args):
        """Customize initial specs with OLS and too early training start."""
        model_specs = create_initial_model_specs(**args)
        model_specs.set_model(OLS)
        model_specs.start_of_training = model_specs.start_of_training - timedelta(
            days=365
        )
        model_identifier = "failing-test model v1"
        return model_specs, model_identifier, "linear-OLS"

    model_map["failing-test"] = test_specs
