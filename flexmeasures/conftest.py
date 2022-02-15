from contextlib import contextmanager
import pytest
from random import random
from datetime import datetime, timedelta
from typing import List, Dict

from isodate import parse_duration
import pandas as pd
import numpy as np
from flask import request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_security import roles_accepted
from werkzeug.exceptions import (
    InternalServerError,
    BadRequest,
    Unauthorized,
    Forbidden,
    Gone,
)

from flexmeasures.app import create as create_app
from flexmeasures.auth.policy import ADMIN_ROLE
from flexmeasures.utils.time_utils import as_server_time
from flexmeasures.data.services.users import create_user
from flexmeasures.data.models.assets import AssetType, Asset
from flexmeasures.data.models.generic_assets import GenericAssetType, GenericAsset
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.weather import WeatherSensor, WeatherSensorType
from flexmeasures.data.models.markets import Market, MarketType
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.user import User, Account, AccountRole


"""
Useful things for all tests.

# App

One application is made per test session.

# Database

Database recreation and cleanup can happen per test (use fresh_db) or per module (use db).
Having tests inside a module share a database makes those tests faster.
Tests that use fresh_db should be put in a separate module to avoid clashing with the module scoped test db.
For example:
- test_api_v1_1.py contains tests that share a module scoped database
- test_api_v1_1_fresh_db.py contains tests that each get a fresh function-scoped database
Further speed-up may be possible by defining a "package" scoped or even "session" scoped database,
but then tests in different modules need to share data and data modifications can lead to tricky debugging.

# Data

Various fixture below set up data that many tests use.
In case a test needs to use such data with a fresh test database,
that test should also use a fixture that requires the fresh_db.
Such fixtures can be recognised by having fresh_db appended to their name.
"""


@pytest.fixture(scope="session")
def app():
    print("APP FIXTURE")
    test_app = create_app(env="testing")

    # Establish an application context before running the tests.
    ctx = test_app.app_context()
    ctx.push()

    yield test_app

    ctx.pop()

    print("DONE WITH APP FIXTURE")


@pytest.fixture(scope="module")
def db(app):
    """Fresh test db per module."""
    with create_test_db(app) as test_db:
        yield test_db


@pytest.fixture(scope="function")
def fresh_db(app):
    """Fresh test db per function."""
    with create_test_db(app) as test_db:
        yield test_db


@contextmanager
def create_test_db(app):
    """
    Provide a db object with the structure freshly created. This assumes a clean database.
    It does clean up after itself when it's done (drops everything).
    """
    print("DB FIXTURE")
    # app is an instance of a flask app, _db a SQLAlchemy DB
    from flexmeasures.data import db as _db

    _db.app = app
    with app.app_context():
        _db.create_all()

    yield _db

    print("DB FIXTURE CLEANUP")
    # Explicitly close DB connection
    _db.session.close()

    _db.drop_all()


@pytest.fixture(scope="module")
def setup_accounts(db) -> Dict[str, Account]:
    return create_test_accounts(db)


@pytest.fixture(scope="function")
def setup_accounts_fresh_db(fresh_db) -> Dict[str, Account]:
    return create_test_accounts(fresh_db)


def create_test_accounts(db) -> Dict[str, Account]:
    prosumer_account_role = AccountRole(name="Prosumer", description="A Prosumer")
    prosumer_account = Account(
        name="Test Prosumer Account", account_roles=[prosumer_account_role]
    )
    db.session.add(prosumer_account)
    supplier_account_role = AccountRole(
        name="Supplier", description="A supplier trading on markets"
    )
    supplier_account = Account(
        name="Test Supplier Account", account_roles=[supplier_account_role]
    )
    db.session.add(supplier_account)
    dummy_account_role = AccountRole(
        name="Dummy", description="A role we haven't hardcoded anywhere"
    )
    dummy_account = Account(
        name="Test Dummy Account", account_roles=[dummy_account_role]
    )
    db.session.add(dummy_account)
    return dict(
        Prosumer=prosumer_account, Supplier=supplier_account, Dummy=dummy_account
    )


@pytest.fixture(scope="module")
def setup_roles_users(db, setup_accounts) -> Dict[str, User]:
    return create_roles_users(db, setup_accounts)


@pytest.fixture(scope="function")
def setup_roles_users_fresh_db(fresh_db, setup_accounts_fresh_db) -> Dict[str, User]:
    return create_roles_users(fresh_db, setup_accounts_fresh_db)


def create_roles_users(db, test_accounts) -> Dict[str, User]:
    """Create a minimal set of roles and users"""
    new_users: List[User] = []
    # Two Prosumer users
    new_users.append(
        create_user(
            username="Test Prosumer User",
            email="test_prosumer_user@seita.nl",
            account_name=test_accounts["Prosumer"].name,
            password="testtest",
            # TODO: test some normal user roles later in our auth progress
            # user_roles=dict(name="", description=""),
        )
    )
    new_users.append(
        create_user(
            username="Test Prosumer User 2",
            email="test_prosumer_user_2@seita.nl",
            account_name=test_accounts["Prosumer"].name,
            password="testtest",
            user_roles=dict(name="account-admin", description="Admin for this account"),
        )
    )
    # A user on an account without any special rights
    new_users.append(
        create_user(
            username="Test Dummy User",
            email="test_dummy_user_3@seita.nl",
            account_name=test_accounts["Dummy"].name,
            password="testtest",
        )
    )
    # A supplier user
    new_users.append(
        create_user(
            username="Test Supplier User",
            email="test_supplier_user_4@seita.nl",
            account_name=test_accounts["Supplier"].name,
            password="testtest",
        )
    )
    # One platform admin
    new_users.append(
        create_user(
            username="Test Admin User",
            email="test_admin_user@seita.nl",
            account_name=test_accounts[
                "Dummy"
            ].name,  # the account does not give rights
            password="testtest",
            user_roles=dict(
                name=ADMIN_ROLE, description="A user who can do everything."
            ),
        )
    )
    return {user.username: user for user in new_users}


@pytest.fixture(scope="module")
def setup_markets(db) -> Dict[str, Market]:
    return create_test_markets(db)


@pytest.fixture(scope="function")
def setup_markets_fresh_db(fresh_db) -> Dict[str, Market]:
    return create_test_markets(fresh_db)


def create_test_markets(db) -> Dict[str, Market]:
    """Create the epex_da market."""

    day_ahead = MarketType(
        name="day_ahead",
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=True,
    )
    db.session.add(day_ahead)
    epex_da = Market(
        name="epex_da",
        market_type_name="day_ahead",
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
        knowledge_horizon_fnc="x_days_ago_at_y_oclock",
        knowledge_horizon_par={"x": 1, "y": 12, "z": "Europe/Paris"},
    )
    db.session.add(epex_da)
    return {"epex_da": epex_da}


@pytest.fixture(scope="module")
def setup_sources(db) -> Dict[str, DataSource]:
    seita_source = DataSource(name="Seita", type="demo script")
    db.session.add(seita_source)
    entsoe_source = DataSource(name="ENTSO-E", type="demo script")
    db.session.add(entsoe_source)
    return {"Seita": seita_source, "ENTSO-E": entsoe_source}


@pytest.fixture(scope="module")
def setup_asset_types(db) -> Dict[str, AssetType]:
    return create_test_asset_types(db)


@pytest.fixture(scope="function")
def setup_asset_types_fresh_db(fresh_db) -> Dict[str, AssetType]:
    return create_test_asset_types(fresh_db)


@pytest.fixture(scope="module")
def setup_generic_assets(
    db, setup_generic_asset_types, setup_accounts
) -> Dict[str, AssetType]:
    """Make some generic assets used throughout."""
    return create_generic_assets(db, setup_generic_asset_types, setup_accounts)


@pytest.fixture(scope="function")
def setup_generic_assets_fresh_db(
    fresh_db, setup_generic_asset_types_fresh_db, setup_accounts_fresh_db
) -> Dict[str, AssetType]:
    """Make some generic assets used throughout."""
    return create_generic_assets(
        fresh_db, setup_generic_asset_types_fresh_db, setup_accounts_fresh_db
    )


def create_generic_assets(db, setup_generic_asset_types, setup_accounts):
    troposphere = GenericAsset(
        name="troposphere", generic_asset_type=setup_generic_asset_types["public_good"]
    )
    db.session.add(troposphere)
    test_battery = GenericAsset(
        name="Test grid connected battery storage",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Prosumer"],
    )
    db.session.add(test_battery)
    test_wind_turbine = GenericAsset(
        name="Test wind turbine",
        generic_asset_type=setup_generic_asset_types["wind"],
        owner=setup_accounts["Supplier"],
    )
    db.session.add(test_wind_turbine)

    return dict(
        troposphere=troposphere,
        test_battery=test_battery,
        test_wind_turbine=test_wind_turbine,
    )


@pytest.fixture(scope="module")
def setup_generic_asset_types(db) -> Dict[str, AssetType]:
    """Make some generic asset types used throughout."""
    return create_generic_asset_types(db)


@pytest.fixture(scope="function")
def setup_generic_asset_types_fresh_db(fresh_db) -> Dict[str, AssetType]:
    """Make some generic asset types used throughout."""
    return create_generic_asset_types(fresh_db)


def create_generic_asset_types(db):
    public_good = GenericAssetType(
        name="public good",
    )
    db.session.add(public_good)
    solar = GenericAssetType(name="solar panel")
    db.session.add(solar)
    wind = GenericAssetType(name="wind turbine")
    db.session.add(wind)
    battery = GenericAssetType(name="battery")
    db.session.add(battery)
    return dict(public_good=public_good, solar=solar, wind=wind, battery=battery)


def create_test_asset_types(db) -> Dict[str, AssetType]:
    """Make some asset types used throughout.
    Deprecated. Remove with Asset model."""

    solar = AssetType(
        name="solar",
        is_producer=True,
        can_curtail=True,
        daily_seasonality=True,
        yearly_seasonality=True,
    )
    db.session.add(solar)
    wind = AssetType(
        name="wind",
        is_producer=True,
        can_curtail=True,
        daily_seasonality=True,
        yearly_seasonality=True,
    )
    db.session.add(wind)
    return dict(solar=solar, wind=wind)


@pytest.fixture(scope="module")
def setup_assets(
    db, setup_roles_users, setup_markets, setup_sources, setup_asset_types
) -> Dict[str, Asset]:
    """Add assets to known test users.
    Deprecated. Remove with Asset model."""

    assets = []
    for asset_name in ["wind-asset-1", "wind-asset-2", "solar-asset-1"]:
        asset = Asset(
            name=asset_name,
            owner_id=setup_roles_users["Test Prosumer User"].id,
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
        db.session.add(asset)
        assets.append(asset)

        # one day of test data (one complete sine curve)
        time_slots = pd.date_range(
            datetime(2015, 1, 1), datetime(2015, 1, 1, 23, 45), freq="15T"
        )
        values = [
            random() * (1 + np.sin(x * 2 * np.pi / (4 * 24)))
            for x in range(len(time_slots))
        ]
        beliefs = [
            TimedBelief(
                event_start=as_server_time(dt),
                belief_horizon=parse_duration("PT0M"),
                event_value=val,
                sensor=asset.corresponding_sensor,
                source=setup_sources["Seita"],
            )
            for dt, val in zip(time_slots, values)
        ]
        db.session.add_all(beliefs)
    return {asset.name: asset for asset in assets}


@pytest.fixture(scope="module")
def setup_beliefs(db: SQLAlchemy, setup_markets, setup_sources) -> int:
    """
    :returns: the number of beliefs set up
    """
    sensor = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    beliefs = [
        TimedBelief(
            sensor=sensor,
            source=setup_sources["ENTSO-E"],
            event_value=21,
            event_start="2021-03-28 16:00+01",
            belief_horizon=timedelta(0),
        ),
        TimedBelief(
            sensor=sensor,
            source=setup_sources["ENTSO-E"],
            event_value=21,
            event_start="2021-03-28 17:00+01",
            belief_horizon=timedelta(0),
        ),
        TimedBelief(
            sensor=sensor,
            source=setup_sources["ENTSO-E"],
            event_value=20,
            event_start="2021-03-28 17:00+01",
            belief_horizon=timedelta(hours=2),
            cp=0.2,
        ),
        TimedBelief(
            sensor=sensor,
            source=setup_sources["ENTSO-E"],
            event_value=21,
            event_start="2021-03-28 17:00+01",
            belief_horizon=timedelta(hours=2),
            cp=0.5,
        ),
    ]
    db.session.add_all(beliefs)
    return len(beliefs)


@pytest.fixture(scope="module")
def add_market_prices(db: SQLAlchemy, setup_assets, setup_markets, setup_sources):
    """Add two days of market prices for the EPEX day-ahead market."""

    # one day of test data (one complete sine curve)
    time_slots = pd.date_range(
        datetime(2015, 1, 1), datetime(2015, 1, 2), freq="1H", closed="left"
    )
    values = [
        random() * (1 + np.sin(x * 2 * np.pi / 24)) for x in range(len(time_slots))
    ]
    day1_beliefs = [
        TimedBelief(
            event_start=as_server_time(dt),
            belief_horizon=timedelta(hours=0),
            event_value=val,
            source=setup_sources["Seita"],
            sensor=setup_markets["epex_da"].corresponding_sensor,
        )
        for dt, val in zip(time_slots, values)
    ]
    db.session.add_all(day1_beliefs)

    # another day of test data (8 expensive hours, 8 cheap hours, and again 8 expensive hours)
    time_slots = pd.date_range(
        datetime(2015, 1, 2), datetime(2015, 1, 3), freq="1H", closed="left"
    )
    values = [100] * 8 + [90] * 8 + [100] * 8
    day2_beliefs = [
        TimedBelief(
            event_start=as_server_time(dt),
            belief_horizon=timedelta(hours=0),
            event_value=val,
            source=setup_sources["Seita"],
            sensor=setup_markets["epex_da"].corresponding_sensor,
        )
        for dt, val in zip(time_slots, values)
    ]
    db.session.add_all(day2_beliefs)


@pytest.fixture(scope="module")
def add_battery_assets(
    db: SQLAlchemy, setup_roles_users, setup_markets
) -> Dict[str, Asset]:
    return create_test_battery_assets(db, setup_roles_users, setup_markets)


@pytest.fixture(scope="function")
def add_battery_assets_fresh_db(
    fresh_db, setup_roles_users_fresh_db, setup_markets_fresh_db
) -> Dict[str, Asset]:
    return create_test_battery_assets(
        fresh_db, setup_roles_users_fresh_db, setup_markets_fresh_db
    )


def create_test_battery_assets(
    db: SQLAlchemy, setup_roles_users, setup_markets
) -> Dict[str, Asset]:
    """Add two battery assets, set their capacity values and their initial SOC."""
    db.session.add(
        AssetType(
            name="battery",
            is_consumer=True,
            is_producer=True,
            can_curtail=True,
            can_shift=True,
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        )
    )

    test_battery = Asset(
        name="Test battery",
        owner_id=setup_roles_users["Test Prosumer User"].id,
        asset_type_name="battery",
        event_resolution=timedelta(minutes=15),
        capacity_in_mw=2,
        max_soc_in_mwh=5,
        min_soc_in_mwh=0,
        soc_in_mwh=2.5,
        soc_datetime=as_server_time(datetime(2015, 1, 1)),
        soc_udi_event_id=203,
        latitude=10,
        longitude=100,
        market_id=setup_markets["epex_da"].id,
        unit="MW",
    )
    db.session.add(test_battery)

    test_battery_no_prices = Asset(
        name="Test battery with no known prices",
        owner_id=setup_roles_users["Test Prosumer User"].id,
        asset_type_name="battery",
        event_resolution=timedelta(minutes=15),
        capacity_in_mw=2,
        max_soc_in_mwh=5,
        min_soc_in_mwh=0,
        soc_in_mwh=2.5,
        soc_datetime=as_server_time(datetime(2040, 1, 1)),
        soc_udi_event_id=203,
        latitude=10,
        longitude=100,
        market_id=setup_markets["epex_da"].id,
        unit="MW",
    )
    db.session.add(test_battery_no_prices)
    return {
        "Test battery": test_battery,
        "Test battery with no known prices": test_battery_no_prices,
    }


@pytest.fixture(scope="module")
def add_charging_station_assets(
    db: SQLAlchemy, setup_roles_users, setup_markets
) -> Dict[str, Asset]:
    """Add uni- and bi-directional charging station assets, set their capacity value and their initial SOC."""
    db.session.add(
        AssetType(
            name="one-way_evse",
            is_consumer=True,
            is_producer=False,
            can_curtail=True,
            can_shift=True,
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        )
    )
    db.session.add(
        AssetType(
            name="two-way_evse",
            is_consumer=True,
            is_producer=True,
            can_curtail=True,
            can_shift=True,
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        )
    )

    charging_station = Asset(
        name="Test charging station",
        owner_id=setup_roles_users["Test Prosumer User"].id,
        asset_type_name="one-way_evse",
        event_resolution=timedelta(minutes=15),
        capacity_in_mw=2,
        max_soc_in_mwh=5,
        min_soc_in_mwh=0,
        soc_in_mwh=2.5,
        soc_datetime=as_server_time(datetime(2015, 1, 1)),
        soc_udi_event_id=203,
        latitude=10,
        longitude=100,
        market_id=setup_markets["epex_da"].id,
        unit="MW",
    )
    db.session.add(charging_station)

    bidirectional_charging_station = Asset(
        name="Test charging station (bidirectional)",
        owner_id=setup_roles_users["Test Prosumer User"].id,
        asset_type_name="two-way_evse",
        event_resolution=timedelta(minutes=15),
        capacity_in_mw=2,
        max_soc_in_mwh=5,
        min_soc_in_mwh=0,
        soc_in_mwh=2.5,
        soc_datetime=as_server_time(datetime(2015, 1, 1)),
        soc_udi_event_id=203,
        latitude=10,
        longitude=100,
        market_id=setup_markets["epex_da"].id,
        unit="MW",
    )
    db.session.add(bidirectional_charging_station)
    return {
        "Test charging station": charging_station,
        "Test charging station (bidirectional)": bidirectional_charging_station,
    }


@pytest.fixture(scope="module")
def add_weather_sensors(db) -> Dict[str, WeatherSensor]:
    return create_weather_sensors(db)


@pytest.fixture(scope="function")
def add_weather_sensors_fresh_db(fresh_db) -> Dict[str, WeatherSensor]:
    return create_weather_sensors(fresh_db)


def create_weather_sensors(db: SQLAlchemy):
    """Add some weather sensors and weather sensor types."""

    test_sensor_type = WeatherSensorType(name="wind_speed")
    db.session.add(test_sensor_type)
    wind_sensor = WeatherSensor(
        name="wind_speed_sensor",
        weather_sensor_type_name="wind_speed",
        event_resolution=timedelta(minutes=5),
        latitude=33.4843866,
        longitude=126,
        unit="m/s",
    )
    db.session.add(wind_sensor)

    test_sensor_type = WeatherSensorType(name="temperature")
    db.session.add(test_sensor_type)
    temp_sensor = WeatherSensor(
        name="temperature_sensor",
        weather_sensor_type_name="temperature",
        event_resolution=timedelta(minutes=5),
        latitude=33.4843866,
        longitude=126.0,
        unit="°C",
    )
    db.session.add(temp_sensor)
    return {"wind": wind_sensor, "temperature": temp_sensor}


@pytest.fixture(scope="module")
def add_sensors(db: SQLAlchemy, setup_generic_assets):
    """Add some generic sensors."""
    height_sensor = Sensor(
        name="height", unit="m", generic_asset=setup_generic_assets["troposphere"]
    )
    db.session.add(height_sensor)
    return height_sensor


@pytest.fixture(scope="module")
def battery_soc_sensor(db: SQLAlchemy, setup_generic_assets):
    """Add a battery SOC sensor."""
    soc_sensor = Sensor(
        name="state of charge",
        unit="%",
        generic_asset=setup_generic_assets["test_battery"],
    )
    db.session.add(soc_sensor)
    return soc_sensor


@pytest.fixture(scope="function")
def clean_redis(app):
    failed = app.queues["forecasting"].failed_job_registry
    app.queues["forecasting"].empty()
    for job_id in failed.get_job_ids():
        failed.remove(app.queues["forecasting"].fetch_job(job_id))


@pytest.fixture(scope="session", autouse=True)
def error_endpoints(app):
    """Adding endpoints for the test session, which can be used to generate errors.
    Adding endpoints only for testing can only be done *before* the first request
    so scope=session and autouse=True are required, as well as adding them in the top
    conftest module."""

    @app.route("/raise-error")
    def error_generator():
        if "type" in request.args:
            if request.args.get("type") == "server_error":
                raise InternalServerError("InternalServerError Test Message")
            if request.args.get("type") == "bad_request":
                raise BadRequest("BadRequest Test Message")
            if request.args.get("type") == "gone":
                raise Gone("Gone Test Message")
            if request.args.get("type") == "unauthorized":
                raise Unauthorized("Unauthorized Test Message")
            if request.args.get("type") == "forbidden":
                raise Forbidden("Forbidden Test Message")
        return jsonify({"message": "Nothing bad happened."}), 200

    @app.route("/protected-endpoint-only-for-admins")
    @roles_accepted(ADMIN_ROLE)
    def vips_only():
        return jsonify({"message": "Nothing bad happened."}), 200
