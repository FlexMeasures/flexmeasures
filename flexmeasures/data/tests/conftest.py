import pytest
from datetime import datetime, timedelta
from random import random
from typing import Dict

from isodate import parse_duration
import pandas as pd
import numpy as np
from flask_sqlalchemy import SQLAlchemy
from statsmodels.api import OLS

from flexmeasures.data.models.annotations import Annotation
from flexmeasures.data.models.assets import Asset
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.models.weather import WeatherSensorType, WeatherSensor
from flexmeasures.data.models.forecasting import model_map
from flexmeasures.data.models.forecasting.model_spec_factory import (
    create_initial_model_specs,
)
from flexmeasures.utils.time_utils import as_server_time


@pytest.fixture(scope="module")
def setup_test_data(
    db,
    app,
    add_market_prices,
    setup_assets,
    remove_seasonality_for_power_forecasts,
):
    """
    Adding a few forecasting jobs (based on data made in flexmeasures.conftest).
    """
    print("Setting up data for data tests on %s" % db.engine)

    add_test_weather_sensor_and_forecasts(db)

    print("Done setting up data for data tests")


@pytest.fixture(scope="function")
def setup_fresh_test_data(
    fresh_db,
    setup_markets_fresh_db,
    setup_roles_users_fresh_db,
    app,
    fresh_remove_seasonality_for_power_forecasts,
):
    db = fresh_db
    setup_roles_users = setup_roles_users_fresh_db
    setup_markets = setup_markets_fresh_db

    data_source = DataSource(name="Seita", type="demo script")
    db.session.add(data_source)
    db.session.flush()

    for asset_name in ["wind-asset-2", "solar-asset-1"]:
        asset = Asset(
            name=asset_name,
            asset_type_name="wind" if "wind" in asset_name else "solar",
            event_resolution=timedelta(minutes=15),
            capacity_in_mw=1,
            latitude=10,
            longitude=100,
            min_soc_in_mwh=0,
            max_soc_in_mwh=0,
            soc_in_mwh=0,
            unit="MW",
            market_id=setup_markets["epex_da"].id,
        )
        asset.owner = setup_roles_users["Test Prosumer User"]
        db.session.add(asset)

        time_slots = pd.date_range(
            datetime(2015, 1, 1), datetime(2015, 1, 1, 23, 45), freq="15T"
        )
        values = [random() * (1 + np.sin(x / 15)) for x in range(len(time_slots))]
        beliefs = [
            TimedBelief(
                event_start=as_server_time(dt),
                belief_horizon=parse_duration("PT0M"),
                event_value=val,
                sensor=asset.corresponding_sensor,
                source=data_source,
            )
            for dt, val in zip(time_slots, values)
        ]
        db.session.add_all(beliefs)
    add_test_weather_sensor_and_forecasts(fresh_db)


@pytest.fixture(scope="module", autouse=True)
def remove_seasonality_for_power_forecasts(db, setup_asset_types):
    """Make sure the AssetType specs make us query only data we actually have in the test db"""
    for asset_type in setup_asset_types.keys():
        setup_asset_types[asset_type].daily_seasonality = False
        setup_asset_types[asset_type].weekly_seasonality = False
        setup_asset_types[asset_type].yearly_seasonality = False


@pytest.fixture(scope="function")
def fresh_remove_seasonality_for_power_forecasts(db, setup_asset_types_fresh_db):
    """Make sure the AssetType specs make us query only data we actually have in the test db"""
    setup_asset_types = setup_asset_types_fresh_db
    for asset_type in setup_asset_types.keys():
        setup_asset_types[asset_type].daily_seasonality = False
        setup_asset_types[asset_type].weekly_seasonality = False
        setup_asset_types[asset_type].yearly_seasonality = False


def add_test_weather_sensor_and_forecasts(db: SQLAlchemy):
    """one day of test data (one complete sine curve) for two sensors"""
    data_source = DataSource.query.filter_by(
        name="Seita", type="demo script"
    ).one_or_none()
    for sensor_name in ("radiation", "wind_speed"):
        sensor_type = WeatherSensorType.query.filter_by(name=sensor_name).one_or_none()
        if sensor_type is None:
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
                TimedBelief(
                    sensor=sensor.corresponding_sensor,
                    event_start=as_server_time(dt),
                    event_value=val,
                    belief_horizon=timedelta(hours=6),
                    source=data_source,
                )
            )


@pytest.fixture(scope="module", autouse=True)
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


@pytest.fixture(scope="module")
def add_nearby_weather_sensors(db, add_weather_sensors) -> Dict[str, WeatherSensor]:
    temp_sensor_location = add_weather_sensors["temperature"].location
    farther_temp_sensor = WeatherSensor(
        name="farther_temperature_sensor",
        weather_sensor_type_name="temperature",
        event_resolution=timedelta(minutes=5),
        latitude=temp_sensor_location[0],
        longitude=temp_sensor_location[1] + 0.1,
        unit="°C",
    )
    even_farther_temp_sensor = WeatherSensor(
        name="even_farther_temperature_sensor",
        weather_sensor_type_name="temperature",
        event_resolution=timedelta(minutes=5),
        latitude=temp_sensor_location[0],
        longitude=temp_sensor_location[1] + 0.2,
        unit="°C",
    )
    db.session.add(farther_temp_sensor)
    db.session.add(even_farther_temp_sensor)
    add_weather_sensors["farther_temperature"] = farther_temp_sensor
    add_weather_sensors["even_farther_temperature"] = even_farther_temp_sensor
    return add_weather_sensors


@pytest.fixture(scope="module")
def setup_annotations(
    db,
    battery_soc_sensor,
    setup_sources,
    app,
):
    """Set up an annotation for an account, an asset and a sensor."""
    sensor = battery_soc_sensor
    asset = sensor.generic_asset
    account = asset.owner
    source = setup_sources["Seita"]
    annotation = Annotation(
        content="Dutch new year",
        start=pd.Timestamp("2020-01-01 00:00+01"),
        end=pd.Timestamp("2020-01-02 00:00+01"),
        source=source,
        type="holiday",
    )
    account.annotations.append(annotation)
    asset.annotations.append(annotation)
    sensor.annotations.append(annotation)
    db.session.flush()
    return dict(
        annotation=annotation,
        account=account,
        asset=asset,
        sensor=sensor,
    )
