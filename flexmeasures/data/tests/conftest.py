from __future__ import annotations
import pytest
from datetime import datetime, timedelta
from random import random
from timely_beliefs.sensors.func_store.knowledge_horizons import at_date
from isodate import parse_duration
from flexmeasures.data.models.planning.utils import initialize_index
import pandas as pd
import numpy as np
from flask_sqlalchemy import SQLAlchemy
from statsmodels.api import OLS

from flexmeasures.data.models.annotations import Annotation
from flexmeasures.data.models.assets import Asset
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief, Sensor
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
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
    setup_generic_asset_types,
    remove_seasonality_for_power_forecasts,
):
    """
    Adding a few forecasting jobs (based on data made in flexmeasures.conftest).
    """
    print("Setting up data for data tests on %s" % db.engine)

    add_test_weather_sensor_and_forecasts(db, setup_generic_asset_types)

    print("Done setting up data for data tests")


@pytest.fixture(scope="function")
def setup_fresh_test_data(
    fresh_db,
    setup_markets_fresh_db,
    setup_roles_users_fresh_db,
    setup_generic_asset_types_fresh_db,
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
                source=DataSource("source1"),
            )
            for dt, val in zip(time_slots, values)
        ]
        db.session.add_all(beliefs)
    add_test_weather_sensor_and_forecasts(fresh_db, setup_generic_asset_types_fresh_db)


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


def add_test_weather_sensor_and_forecasts(db: SQLAlchemy, setup_generic_asset_types):
    """one day of test data (one complete sine curve) for two sensors"""
    weather_station = GenericAsset(
        name="Test weather station farther away",
        generic_asset_type=setup_generic_asset_types["weather_station"],
        latitude=100,
        longitude=100,
    )
    for sensor_name, unit in (("irradiance", "kW/m²"), ("wind speed", "m/s")):
        sensor = Sensor(name=sensor_name, generic_asset=weather_station, unit=unit)
        db.session.add(sensor)
        time_slots = pd.date_range(
            datetime(2015, 1, 1), datetime(2015, 1, 2, 23, 45), freq="15T"
        )
        values = [random() * (1 + np.sin(x / 15)) for x in range(len(time_slots))]
        if sensor_name == "temperature":
            values = [value * 17 for value in values]
        if sensor_name == "wind speed":
            values = [value * 45 for value in values]
        if sensor_name == "irradiance":
            values = [value * 600 for value in values]
        for dt, val in zip(time_slots, values):
            db.session.add(
                TimedBelief(
                    sensor=sensor,
                    event_start=as_server_time(dt),
                    event_value=val,
                    belief_horizon=timedelta(hours=6),
                    source=DataSource("source1"),
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
def add_nearby_weather_sensors(db, add_weather_sensors) -> dict[str, Sensor]:
    temp_sensor_location = add_weather_sensors["temperature"].generic_asset.location
    weather_station_type = GenericAssetType.query.filter(
        GenericAssetType.name == "weather station"
    ).one_or_none()
    farther_weather_station = GenericAsset(
        name="Test weather station farther away",
        generic_asset_type=weather_station_type,
        latitude=temp_sensor_location[0],
        longitude=temp_sensor_location[1] + 0.1,
    )
    db.session.add(farther_weather_station)
    farther_temp_sensor = Sensor(
        name="temperature",
        generic_asset=farther_weather_station,
        event_resolution=timedelta(minutes=5),
        unit="°C",
    )
    db.session.add(farther_temp_sensor)
    even_farther_weather_station = GenericAsset(
        name="Test weather station even farther away",
        generic_asset_type=weather_station_type,
        latitude=temp_sensor_location[0],
        longitude=temp_sensor_location[1] + 0.2,
    )
    db.session.add(even_farther_weather_station)
    even_farther_temp_sensor = Sensor(
        name="temperature",
        generic_asset=even_farther_weather_station,
        event_resolution=timedelta(minutes=5),
        unit="°C",
    )
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


@pytest.fixture(scope="module")
def create_solar_plants(db, setup_accounts, setup_sources) -> dict[str, Sensor]:
    """Create Solar Plants and their Power and Price sensor along with their beliefs."""
    asset_type = GenericAssetType(
        name="Solar",
    )
    db.session.add(asset_type)
    Solar1 = GenericAsset(
        name="solar-1",
        generic_asset_type=asset_type,
    )
    db.session.add(Solar1)
    solar1_production_price_sensor = Sensor(
        name="solar1-production-price-sensor",
        generic_asset=Solar1,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
        knowledge_horizon=(at_date, {"knowledge_time": "2014-11-01T00:00+01:00"}),
    )
    db.session.add(solar1_production_price_sensor)
    production_price = TimedBelief(
        event_start="2015-01-01T00:00+01:00",
        belief_time="2014-11-01T00:00+01:00",  # publication date
        event_value=2,
        source=setup_sources["Seita"],
        sensor=solar1_production_price_sensor,
    )
    db.session.add(production_price)
    solar1_power_sensor = Sensor(
        name="solar-power-1",
        generic_asset=Solar1,
        event_resolution=timedelta(hours=1),
        unit="MW",
        attributes={"capacity_in_mw": 2000},
    )
    db.session.add(solar1_power_sensor)
    time_slots = initialize_index(
        start=pd.Timestamp("2015-01-01").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2015-01-02").tz_localize("Europe/Amsterdam"),
        resolution="1H",
    )
    values = [0] * 5 + list(range(7, 51, 7)) + list(range(50, 0, -7)) + [0] * 5
    add_as_beliefs(db, solar1_power_sensor, values, time_slots, setup_sources["Seita"])
    Solar2 = GenericAsset(
        name="solar-2",
        generic_asset_type=asset_type,
    )
    db.session.add(Solar2)
    solar2_production_price_sensor = Sensor(
        name="solar2-production-price-sensor",
        generic_asset=Solar2,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
        knowledge_horizon=(at_date, {"knowledge_time": "2014-11-01T00:00+01:00"}),
    )
    db.session.add(solar2_production_price_sensor)
    production_price = TimedBelief(
        event_start="2015-01-01T00:00+01:00",
        belief_time="2014-11-01T00:00+01:00",  # publication date
        event_value=2.5,
        source=setup_sources["Seita"],
        sensor=solar2_production_price_sensor,
    )
    db.session.add(production_price)
    solar2_power_sensor = Sensor(
        name="solar-power-2",
        generic_asset=Solar2,
        event_resolution=timedelta(hours=1),
        unit="MW",
        attributes={"capacity_in_mw": 2000},
    )
    db.session.add(solar2_power_sensor)
    time_slots = initialize_index(
        start=pd.Timestamp("2015-01-01").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2015-01-02").tz_localize("Europe/Amsterdam"),
        resolution="1H",
    )
    values = [0] * 5 + list(range(7, 51, 7)) + list(range(50, 0, -7)) + [0] * 5
    add_as_beliefs(db, solar2_power_sensor, values, time_slots, setup_sources["Seita"])
    Solar3 = GenericAsset(
        name="solar-3",
        generic_asset_type=asset_type,
    )
    db.session.add(Solar3)
    solar3_production_price_sensor = Sensor(
        name="solar3-production-price-sensor",
        generic_asset=Solar3,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
        knowledge_horizon=(at_date, {"knowledge_time": "2014-11-01T00:00+01:00"}),
    )
    db.session.add(solar3_production_price_sensor)
    production_price = TimedBelief(
        event_start="2015-01-01T00:00+01:00",
        belief_time="2014-11-01T00:00+01:00",  # publication date
        event_value=3,
        source=setup_sources["Seita"],
        sensor=solar3_production_price_sensor,
    )
    db.session.add(production_price)
    solar3_power_sensor = Sensor(
        name="solar-power-3",
        generic_asset=Solar3,
        event_resolution=timedelta(hours=1),
        unit="MW",
        attributes={"capacity_in_mw": 2000},
    )
    db.session.add(solar3_power_sensor)
    time_slots = initialize_index(
        start=pd.Timestamp("2015-01-01").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2015-01-02").tz_localize("Europe/Amsterdam"),
        resolution="1H",
    )
    values = [0] * 5 + list(range(7, 51, 7)) + list(range(50, 0, -7)) + [0] * 5
    add_as_beliefs(
        db, solar3_power_sensor, values, time_slots, setup_sources["Seita"]
    )  # make sure that prices are assigned to price sensors
    db.session.flush()
    return (
        solar1_production_price_sensor,
        solar1_power_sensor,
        solar2_production_price_sensor,
        solar2_power_sensor,
        solar3_production_price_sensor,
        solar3_power_sensor,
    )


@pytest.fixture(scope="module")
def create_building(db, setup_sources) -> dict[str, Sensor]:
    """
    Set up a building.
    """
    asset_type = GenericAssetType(
        name="Building",
    )
    db.session.add(asset_type)
    Building = GenericAsset(
        name="building",
        generic_asset_type=asset_type,
    )
    db.session.add(Building)
    building_consumption_price_sensor = Sensor(
        name="building-consumption-price-sensor",
        generic_asset=Building,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
        knowledge_horizon=(at_date, {"knowledge_time": "2014-11-01T00:00+01:00"}),
    )
    db.session.add(building_consumption_price_sensor)
    building_power = Sensor(
        name="building-power",
        generic_asset=Building,
        event_resolution=timedelta(hours=1),
        unit="MW",
        attributes={"capacity_in_mw": 2000},
    )
    db.session.add(building_power)
    time_slots = initialize_index(
        start=pd.Timestamp("2015-01-01").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2015-01-02").tz_localize("Europe/Amsterdam"),
        resolution="1H",
    )
    values = (
        [-30] * 1
        + list(range(-50, -210, -30))
        + list(range(-197, -40, 30))
        + list(range(-50, -210, -30))
        + list(range(-197, -70, 30))
    )
    add_as_beliefs(db, building_power, values, time_slots, setup_sources["Seita"])
    db.session.flush()
    return building_consumption_price_sensor, building_power


@pytest.fixture(scope="module")
def flexible_devices(db, setup_sources) -> dict[str, Sensor]:
    """
    Set up sensors for flexible devices:
    - Battery
    - Transmission Grid
    """
    asset_type = GenericAssetType(
        name="test-Battery",
    )
    db.session.add(asset_type)
    Battery = GenericAsset(
        name="battery",
        generic_asset_type=asset_type,
        attributes=dict(
            capacity_in_mw=800,
            max_soc_in_mwh=795,
            min_soc_in_mwh=0.5,
        ),
    )
    db.session.add(Battery)
    battery_consumption_price_sensor = Sensor(
        name="battery-consumption-price-sensor",
        generic_asset=Battery,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
        knowledge_horizon=(at_date, {"knowledge_time": "2014-11-01T00:00+01:00"}),
    )
    db.session.add(battery_consumption_price_sensor)
    battery_production_price_sensor = Sensor(
        name="battery-production-price-sensor",
        generic_asset=Battery,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
        knowledge_horizon=(at_date, {"knowledge_time": "2014-11-01T00:00+01:00"}),
    )
    db.session.add(battery_production_price_sensor)
    battery_power = Sensor(
        name="battery-power",
        generic_asset=Battery,
        event_resolution=timedelta(hours=1),
        unit="MW",
        attributes={"capacity_in_mw": 2000},
    )
    db.session.add(battery_power)
    asset_type = GenericAssetType(
        name="Transmission-Grid",
    )
    db.session.add(asset_type)
    Grid = GenericAsset(
        name="grid",
        generic_asset_type=asset_type,
    )
    db.session.add(Grid)
    grid_consumption_price_sensor = Sensor(
        name="grid-consumption-price-sensor",
        generic_asset=Grid,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
        knowledge_horizon=(at_date, {"knowledge_time": "2014-11-01T00:00+01:00"}),
    )
    db.session.add(grid_consumption_price_sensor)
    time_slots = initialize_index(
        start=pd.Timestamp("2015-01-01").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2015-01-02").tz_localize("Europe/Amsterdam"),
        resolution="1H",
    )
    values = [
        9.63,
        8.66,
        8.387,
        8.387,
        9.6,
        9.722,
        9.907,
        11.777,
        10.237,
        7.999,
        7.08,
        6.5,
        5.999,
        5.233,
        5,
        5,
        4.5,
        5.03,
        5.8,
        7.105,
        10.012,
        12.494,
        11.825,
        10.396,
    ]
    add_as_beliefs(
        db, grid_consumption_price_sensor, values, time_slots, setup_sources["Seita"]
    )
    grid_production_price_sensor = Sensor(
        name="grid-production-price-sensor",
        generic_asset=Grid,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
        knowledge_horizon=(at_date, {"knowledge_time": "2014-11-01T00:00+01:00"}),
    )
    db.session.add(grid_production_price_sensor)
    time_slots = initialize_index(
        start=pd.Timestamp("2015-01-01").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2015-01-02").tz_localize("Europe/Amsterdam"),
        resolution="1H",
    )
    values = [
        9.63,
        8.66,
        8.387,
        8.387,
        9.6,
        9.722,
        9.907,
        11.777,
        10.237,
        7.999,
        7.08,
        6.5,
        5.999,
        5.233,
        5,
        5,
        4.5,
        5.03,
        5.8,
        7.105,
        10.012,
        12.494,
        11.825,
        10.396,
    ]
    add_as_beliefs(
        db, grid_production_price_sensor, values, time_slots, setup_sources["Seita"]
    )
    grid_power = Sensor(
        name="Grid-power",
        generic_asset=Grid,
        event_resolution=timedelta(hours=1),
        unit="MW",
        attributes={"capacity_in_mw": 20000},
    )
    db.session.add(grid_power)
    db.session.flush()
    return (
        battery_consumption_price_sensor,
        battery_production_price_sensor,
        battery_power,
        grid_consumption_price_sensor,
        grid_production_price_sensor,
        grid_power,
    )


def add_as_beliefs(db, sensor, values, time_slots, source):
    beliefs = [
        TimedBelief(
            event_start=dt,
            belief_time=time_slots[0],
            event_value=val,
            source=source,
            sensor=sensor,
        )
        for dt, val in zip(time_slots, values)
    ]
    db.session.add_all(beliefs)
    db.session.commit()
