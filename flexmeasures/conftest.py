from __future__ import annotations

from contextlib import contextmanager
import pytest
from random import random, seed
from datetime import datetime, timedelta
from sqlalchemy import select
from isodate import parse_duration
import pandas as pd
import numpy as np
from flask import request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_security import roles_accepted
from pytest_mock import MockerFixture
from timely_beliefs.sensors.func_store.knowledge_horizons import x_days_ago_at_y_oclock

from werkzeug.exceptions import (
    InternalServerError,
    BadRequest,
    Unauthorized,
    Forbidden,
    Gone,
)

from flexmeasures.app import create as create_app
from flexmeasures.auth.policy import ADMIN_ROLE, ADMIN_READER_ROLE
from flexmeasures.data.services.users import create_user
from flexmeasures.data.models.generic_assets import GenericAssetType, GenericAsset
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.planning.utils import initialize_index
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

    with test_app.app_context():
        yield test_app

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
def setup_accounts(db) -> dict[str, Account]:
    return create_test_accounts(db)


@pytest.fixture(scope="function")
def setup_accounts_fresh_db(fresh_db) -> dict[str, Account]:
    return create_test_accounts(fresh_db)


def create_test_accounts(db) -> dict[str, Account]:
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
    empty_account = Account(name="Test Empty Account")
    db.session.add(empty_account)
    multi_role_account = Account(
        name="Multi Role Account",
        account_roles=[
            prosumer_account_role,
            supplier_account_role,
            dummy_account_role,
        ],
    )
    db.session.add(multi_role_account)
    consultancy_account_role = AccountRole(
        name="Consultancy", description="A consultancy account"
    )
    # Create Consultancy and ConsultancyClient account.
    # The ConsultancyClient account needs the account id of the Consultancy account so the order is important.
    consultancy_account = Account(
        name="Test Consultancy Account", account_roles=[consultancy_account_role]
    )
    db.session.add(consultancy_account)
    consultancy_client_account_role = AccountRole(
        name="ConsultancyClient",
        description="A client of a consultancy",
    )
    consultancy_account_id = (
        db.session.execute(select(Account).filter_by(name="Test Consultancy Account"))
        .scalar_one_or_none()
        .id
    )
    consultancy_client_account = Account(
        name="Test ConsultancyClient Account",
        account_roles=[consultancy_client_account_role],
        consultancy_account_id=consultancy_account_id,
    )
    db.session.add(consultancy_client_account)
    return dict(
        Prosumer=prosumer_account,
        Supplier=supplier_account,
        Dummy=dummy_account,
        Empty=empty_account,
        Multi=multi_role_account,
        Consultancy=consultancy_account,
        ConsultancyClient=consultancy_client_account,
    )


@pytest.fixture(scope="module")
def setup_roles_users(db, setup_accounts) -> dict[str, User]:
    return create_roles_users(db, setup_accounts)


@pytest.fixture(scope="function")
def setup_roles_users_fresh_db(fresh_db, setup_accounts_fresh_db) -> dict[str, User]:
    return create_roles_users(fresh_db, setup_accounts_fresh_db)


def create_roles_users(db, test_accounts) -> dict[str, User]:
    """Create a minimal set of roles and users"""
    new_users: list[User] = []
    # 3 Prosumer users: 2 plain ones, 1 account admin
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
    new_users.append(
        create_user(
            username="Test Another Plain Prosumer User",
            email="test_prosumer_user_3@seita.nl",
            account_name=test_accounts["Prosumer"].name,
            password="testtest",
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
    # Account admin on dummy account
    new_users.append(
        create_user(
            username="Test Dummy Account Admin",
            email="test_dummy_account_admin@seita.nl",
            account_name=test_accounts["Dummy"].name,
            password="testtest",
            user_roles=dict(name="account-admin", description="Admin for this account"),
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
    # One platform admin reader
    new_users.append(
        create_user(
            username="Test Admin Reader User",
            email="test_admin_reader_user@seita.nl",
            account_name=test_accounts[
                "Dummy"
            ].name,  # the account does not give rights
            password="testtest",
            user_roles=dict(
                name=ADMIN_READER_ROLE, description="A user who can do everything."
            ),
        )
    )
    new_users.append(
        create_user(
            username="Test Consultant User",
            email="test_consultant@seita.nl",
            account_name=test_accounts["Consultancy"].name,
            password="testtest",
            user_roles=dict(name="consultant"),
        )
    )
    new_users.append(
        create_user(
            username="Test Consultant User without consultant role",
            email="test_consultancy_user_without_consultant_access@seita.nl",
            account_name=test_accounts["Consultancy"].name,
            password="testtest",
        )
    )
    # Consultancy client account user
    new_users.append(
        create_user(
            username="Test Consultancy Client User",
            email="test_consultant_client@seita.nl",
            account_name=test_accounts["ConsultancyClient"].name,
            password="testtest",
        )
    )
    return {user.username: user.id for user in new_users}


@pytest.fixture(scope="module")
def setup_markets(db) -> dict[str, Sensor]:
    return create_test_markets(db)


@pytest.fixture(scope="function")
def setup_markets_fresh_db(fresh_db) -> dict[str, Sensor]:
    return create_test_markets(fresh_db)


def create_test_markets(db) -> dict[str, Sensor]:
    """Create the epex_da market."""

    day_ahead = GenericAssetType(
        name="day_ahead",
    )
    epex = GenericAsset(
        name="epex",
        generic_asset_type=day_ahead,
    )
    price_sensors = {}
    for sensor_name in ("epex_da", "epex_da_production"):
        price_sensor = Sensor(
            name=sensor_name,
            generic_asset=epex,
            event_resolution=timedelta(hours=1),
            unit="EUR/MWh",
            knowledge_horizon=(
                x_days_ago_at_y_oclock,
                {"x": 1, "y": 12, "z": "Europe/Paris"},
            ),
            attributes=dict(
                daily_seasonality=True,
                weekly_seasonality=True,
                yearly_seasonality=True,
            ),
        )
        db.session.add(price_sensor)
        price_sensors[sensor_name] = price_sensor
    db.session.flush()  # assign an id, so the markets can be used to set a market_id attribute on a GenericAsset or Sensor
    return price_sensors


@pytest.fixture(scope="module")
def setup_sources(db) -> dict[str, DataSource]:
    return create_sources(db)


@pytest.fixture(scope="function")
def setup_sources_fresh_db(fresh_db) -> dict[str, DataSource]:
    return create_sources(fresh_db)


def create_sources(db) -> dict[str, DataSource]:
    seita_source = DataSource(name="Seita", type="demo script")
    db.session.add(seita_source)
    entsoe_source = DataSource(name="ENTSO-E", type="demo script")
    db.session.add(entsoe_source)
    dummy_schedule_source = DataSource(name="DummySchedule", type="demo script")
    db.session.add(dummy_schedule_source)
    return {
        "Seita": seita_source,
        "ENTSO-E": entsoe_source,
        "DummySchedule": dummy_schedule_source,
    }


@pytest.fixture(scope="module")
def setup_generic_assets(
    db, setup_generic_asset_types, setup_accounts
) -> dict[str, GenericAsset]:
    """Make some generic assets used throughout."""
    return create_generic_assets(db, setup_generic_asset_types, setup_accounts)


@pytest.fixture(scope="function")
def setup_generic_assets_fresh_db(
    fresh_db, setup_generic_asset_types_fresh_db, setup_accounts_fresh_db
) -> dict[str, GenericAsset]:
    """Make some generic assets used throughout."""
    return create_generic_assets(
        fresh_db, setup_generic_asset_types_fresh_db, setup_accounts_fresh_db
    )


def create_generic_assets(
    db, setup_generic_asset_types, setup_accounts
) -> dict[str, GenericAsset]:
    troposphere = GenericAsset(
        name="troposphere", generic_asset_type=setup_generic_asset_types["public_good"]
    )
    db.session.add(troposphere)
    test_battery = GenericAsset(
        name="Test grid connected battery storage",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Prosumer"],
        attributes={"some-attribute": "some-value", "sensors_to_show": [1, 2]},
    )
    db.session.add(test_battery)
    test_wind_turbine = GenericAsset(
        name="Test wind turbine",
        generic_asset_type=setup_generic_asset_types["wind"],
        owner=setup_accounts["Supplier"],
    )
    db.session.add(test_wind_turbine)
    test_consultancy_client_asset = GenericAsset(
        name="Test ConsultancyClient Asset",
        generic_asset_type=setup_generic_asset_types["wind"],
        owner=setup_accounts["ConsultancyClient"],
    )
    db.session.add(test_consultancy_client_asset)

    return dict(
        troposphere=troposphere,
        test_battery=test_battery,
        test_wind_turbine=test_wind_turbine,
        test_consultancy_client_asset=test_consultancy_client_asset,
    )


@pytest.fixture(scope="module")
def setup_generic_asset_types(db) -> dict[str, GenericAssetType]:
    """Make some generic asset types used throughout."""
    return create_generic_asset_types(db)


@pytest.fixture(scope="function")
def setup_generic_asset_types_fresh_db(fresh_db) -> dict[str, GenericAssetType]:
    """Make some generic asset types used throughout."""
    return create_generic_asset_types(fresh_db)


def create_generic_asset_types(db) -> dict[str, GenericAssetType]:
    public_good = GenericAssetType(
        name="public good",
    )
    db.session.add(public_good)
    solar = GenericAssetType(name="solar panel")
    db.session.add(solar)
    wind = GenericAssetType(name="wind turbine")
    db.session.add(wind)
    battery = db.session.execute(
        select(GenericAssetType).filter_by(name="battery")
    ).scalar_one_or_none()
    if (
        not battery
    ):  # legacy if-block, because create_test_battery_assets might have created it already - refactor!
        battery = GenericAssetType(name="battery")
    db.session.add(battery)
    weather_station = GenericAssetType(name="weather station")
    db.session.add(weather_station)
    return dict(
        public_good=public_good,
        solar=solar,
        wind=wind,
        battery=battery,
        weather_station=weather_station,
    )


@pytest.fixture(scope="module")
def setup_assets(
    db, setup_accounts, setup_markets, setup_sources, setup_generic_asset_types
) -> dict[str, GenericAsset]:
    return create_assets(
        db, setup_accounts, setup_markets, setup_sources, setup_generic_asset_types
    )


@pytest.fixture(scope="function")
def setup_assets_fresh_db(
    fresh_db,
    setup_accounts_fresh_db,
    setup_markets_fresh_db,
    setup_sources_fresh_db,
    setup_generic_asset_types_fresh_db,
) -> dict[str, GenericAsset]:
    return create_assets(
        fresh_db,
        setup_accounts_fresh_db,
        setup_markets_fresh_db,
        setup_sources_fresh_db,
        setup_generic_asset_types_fresh_db,
    )


def create_assets(
    db, setup_accounts, setup_markets, setup_sources, setup_asset_types
) -> dict[str, GenericAsset]:
    """Add assets with power sensors to known test accounts."""

    assets = []
    for asset_name in ["wind-asset-1", "wind-asset-2", "solar-asset-1"]:
        asset = GenericAsset(
            name=asset_name,
            generic_asset_type=setup_asset_types["wind"]
            if "wind" in asset_name
            else setup_asset_types["solar"],
            owner=setup_accounts["Prosumer"],
            latitude=10,
            longitude=100,
            attributes=dict(
                capacity_in_mw=1,
                min_soc_in_mwh=0,
                max_soc_in_mwh=0,
                soc_in_mwh=0,
                market_id=setup_markets["epex_da"].id,
                is_producer=True,
                can_curtail=True,
            ),
        )
        sensor = Sensor(
            name="power",
            generic_asset=asset,
            event_resolution=timedelta(minutes=15),
            unit="MW",
            attributes=dict(
                daily_seasonality=True,
                yearly_seasonality=True,
            ),
        )
        db.session.add(sensor)
        assets.append(asset)

        # one day of test data (one complete sine curve)
        time_slots = pd.date_range(
            datetime(2015, 1, 1), datetime(2015, 1, 1, 23, 45), freq="15T"
        ).tz_localize("UTC")
        seed(42)  # ensure same results over different test runs
        add_beliefs(
            db=db,
            sensor=sensor,
            time_slots=time_slots,
            values=[
                random() * (1 + np.sin(x * 2 * np.pi / (4 * 24)))
                for x in range(len(time_slots))
            ],
            source=setup_sources["Seita"],
        )
    db.session.commit()
    return {asset.name: asset for asset in assets}


@pytest.fixture(scope="module")
def setup_beliefs(db, setup_markets, setup_sources) -> int:
    """
    Make some beliefs.

    :returns: the number of beliefs set up
    """
    return create_beliefs(db, setup_markets, setup_sources)


@pytest.fixture(scope="function")
def setup_beliefs_fresh_db(
    fresh_db, setup_markets_fresh_db, setup_sources_fresh_db
) -> int:
    """
    Make some beliefs.

    :returns: the number of beliefs set up
    """
    return create_beliefs(fresh_db, setup_markets_fresh_db, setup_sources_fresh_db)


def create_beliefs(db: SQLAlchemy, setup_markets, setup_sources) -> int:
    """
    :returns: the number of beliefs set up
    """
    sensor = db.session.execute(
        select(Sensor).filter(Sensor.name == "epex_da")
    ).scalar_one_or_none()
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
def add_market_prices(
    db: SQLAlchemy, setup_assets, setup_markets, setup_sources
) -> dict[str, Sensor]:
    return add_market_prices_common(db, setup_assets, setup_markets, setup_sources)


@pytest.fixture(scope="function")
def add_market_prices_fresh_db(
    fresh_db: SQLAlchemy,
    setup_assets_fresh_db,
    setup_markets_fresh_db,
    setup_sources_fresh_db,
) -> dict[str, Sensor]:
    return add_market_prices_common(
        fresh_db, setup_assets_fresh_db, setup_markets_fresh_db, setup_sources_fresh_db
    )


def add_market_prices_common(
    db: SQLAlchemy, setup_assets, setup_markets, setup_sources
) -> dict[str, Sensor]:
    """Add three days of market prices for the EPEX day-ahead market."""

    # one day of test data (one complete sine curve)
    time_slots = initialize_index(
        start=pd.Timestamp("2015-01-01").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2015-01-02").tz_localize("Europe/Amsterdam"),
        resolution="1H",
    )
    seed(42)  # ensure same results over different test runs
    add_beliefs(
        db=db,
        sensor=setup_markets["epex_da"],
        time_slots=time_slots,
        values=[
            random() * (1 + np.sin(x * 2 * np.pi / 24)) for x in range(len(time_slots))
        ],
        source=setup_sources["Seita"],
    )

    add_beliefs(
        db=db,
        sensor=setup_markets["epex_da_production"],
        time_slots=time_slots,
        values=[
            random() * (1 + np.sin(x * 2 * np.pi / 24)) for x in range(len(time_slots))
        ],
        source=setup_sources["Seita"],
    )

    # another day of test data (8 expensive hours, 8 cheap hours, and again 8 expensive hours)
    time_slots = initialize_index(
        start=pd.Timestamp("2015-01-02").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2015-01-03").tz_localize("Europe/Amsterdam"),
        resolution="1H",
    )
    add_beliefs(
        db=db,
        sensor=setup_markets["epex_da"],
        time_slots=time_slots,
        values=[100] * 8 + [90] * 8 + [100] * 8,
        source=setup_sources["Seita"],
    )

    # the third day of test data (8 hours with negative prices, followed by 16 expensive hours)
    time_slots = initialize_index(
        start=pd.Timestamp("2015-01-03").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2015-01-04").tz_localize("Europe/Amsterdam"),
        resolution="1H",
    )

    # consumption prices
    add_beliefs(
        db=db,
        sensor=setup_markets["epex_da"],
        time_slots=time_slots,
        values=[-10] * 8 + [100] * 16,
        source=setup_sources["Seita"],
    )

    # production prices = consumption prices - 40
    add_beliefs(
        db=db,
        sensor=setup_markets["epex_da_production"],
        time_slots=time_slots,
        values=[-50] * 8 + [60] * 16,
        source=setup_sources["Seita"],
    )

    # consumption prices for staleness tests
    time_slots = initialize_index(
        start=pd.Timestamp("2016-01-01").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2016-01-03").tz_localize("Europe/Amsterdam"),
        resolution="1H",
    )
    values_today = [
        random() * (1 + np.sin(x * 2 * np.pi / 24)) for x in range(len(time_slots))
    ]

    today_beliefs = [
        TimedBelief(
            event_start=dt,
            belief_horizon=timedelta(hours=0),
            event_value=val,
            source=setup_sources["Seita"],
            sensor=setup_markets["epex_da"],
        )
        for dt, val in zip(time_slots, values_today)
    ]
    db.session.add_all(today_beliefs)

    return {
        "epex_da": setup_markets["epex_da"],
        "epex_da_production": setup_markets["epex_da_production"],
    }


@pytest.fixture(scope="module")
def add_battery_assets(
    db: SQLAlchemy,
    setup_roles_users,
    setup_accounts,
    setup_markets,
    setup_generic_asset_types,
) -> dict[str, GenericAsset]:
    return create_test_battery_assets(
        db, setup_accounts, setup_markets, setup_generic_asset_types
    )


@pytest.fixture(scope="function")
def add_battery_assets_fresh_db(
    fresh_db,
    setup_roles_users_fresh_db,
    setup_accounts_fresh_db,
    setup_markets_fresh_db,
    setup_generic_asset_types_fresh_db,
) -> dict[str, GenericAsset]:
    return create_test_battery_assets(
        fresh_db,
        setup_accounts_fresh_db,
        setup_markets_fresh_db,
        setup_generic_asset_types_fresh_db,
    )


def create_test_battery_assets(
    db: SQLAlchemy, setup_accounts, setup_markets, generic_asset_types
) -> dict[str, GenericAsset]:
    """
    Add two battery assets, set their capacity values and their initial SOC.
    """
    building_type = GenericAssetType(name="building")
    db.session.add(building_type)
    test_building = GenericAsset(
        name="building",
        generic_asset_type=building_type,
        owner=setup_accounts["Prosumer"],
        attributes=dict(
            capacity_in_mw=2,
        ),
    )
    db.session.add(test_building)
    db.session.flush()

    battery_type = generic_asset_types["battery"]

    test_battery = GenericAsset(
        name="Test battery",
        owner=setup_accounts["Prosumer"],
        generic_asset_type=battery_type,
        latitude=10,
        longitude=100,
        parent_asset_id=test_building.id,
        attributes=dict(
            capacity_in_mw=2,
            max_soc_in_mwh=5,
            min_soc_in_mwh=0,
            soc_in_mwh=2.5,
            soc_datetime="2015-01-01T00:00+01",
            soc_udi_event_id=203,
            market_id=setup_markets["epex_da"].id,
            is_consumer=True,
            is_producer=True,
            can_curtail=True,
            can_shift=True,
        ),
    )
    test_battery_sensor = Sensor(
        name="power",
        generic_asset=test_battery,
        event_resolution=timedelta(minutes=15),
        unit="MW",
        attributes=dict(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        ),
    )
    db.session.add(test_battery_sensor)

    test_battery_sensor_kw = Sensor(
        name="power (kW)",
        generic_asset=test_battery,
        event_resolution=timedelta(minutes=15),
        unit="kW",
        attributes=dict(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        ),
    )
    db.session.add(test_battery_sensor_kw)

    test_battery_no_prices = GenericAsset(
        name="Test battery with no known prices",
        owner=setup_accounts["Prosumer"],
        generic_asset_type=battery_type,
        latitude=10,
        longitude=100,
        attributes=dict(
            capacity_in_mw=2,
            max_soc_in_mwh=5,
            min_soc_in_mwh=0,
            soc_in_mwh=2.5,
            soc_datetime="2040-01-01T00:00+01",
            soc_udi_event_id=203,
            market_id=setup_markets["epex_da"].id,
            is_consumer=True,
            is_producer=True,
            can_curtail=True,
            can_shift=True,
        ),
    )
    test_battery_sensor_no_prices = Sensor(
        name="power",
        generic_asset=test_battery_no_prices,
        event_resolution=timedelta(minutes=15),
        unit="MW",
        attributes=dict(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        ),
    )
    db.session.add(test_battery_sensor_no_prices)

    test_battery_dynamic_power_capacity = GenericAsset(
        name="Test battery with dynamic power capacity",
        owner=setup_accounts["Prosumer"],
        generic_asset_type=battery_type,
        latitude=10,
        longitude=100,
        attributes=dict(
            capacity_in_mw=10,
            max_soc_in_mwh=20,
            min_soc_in_mwh=0,
            soc_in_mwh=2.0,
            market_id=setup_markets["epex_da"].id,
        ),
    )
    test_battery_dynamic_capacity_power_sensor = Sensor(
        name="power",
        generic_asset=test_battery_dynamic_power_capacity,
        event_resolution=timedelta(minutes=15),
        unit="MW",
        attributes=dict(
            capacity_in_mw=10,
            production_capacity="8 MW",
            consumption_capacity="0.5 MW",
        ),
    )
    db.session.add(test_battery_dynamic_capacity_power_sensor)

    test_small_battery = GenericAsset(
        name="Test small battery",
        owner=setup_accounts["Prosumer"],
        generic_asset_type=battery_type,
        latitude=10,
        longitude=100,
        attributes=dict(
            capacity_in_mw=0.01,
            max_soc_in_mwh=0.01,
            min_soc_in_mwh=0,
            soc_in_mwh=0.005,
            soc_datetime="2040-01-01T00:00+01",
            soc_udi_event_id=203,
            market_id=setup_markets["epex_da"].id,
            is_consumer=True,
            is_producer=True,
            can_curtail=True,
            can_shift=True,
        ),
    )

    test_battery_sensor_small = Sensor(
        name="power",
        generic_asset=test_small_battery,
        event_resolution=timedelta(minutes=15),
        unit="MW",
        attributes=dict(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        ),
    )
    db.session.add(test_battery_sensor_small)

    db.session.flush()
    return {
        "Test building": test_building,
        "Test battery": test_battery,
        "Test battery with no known prices": test_battery_no_prices,
        "Test small battery": test_small_battery,
        "Test battery with dynamic power capacity": test_battery_dynamic_power_capacity,
    }


@pytest.fixture(scope="module")
def add_charging_station_assets(
    db: SQLAlchemy, setup_accounts, setup_markets
) -> dict[str, GenericAsset]:
    return create_charging_station_assets(db, setup_accounts, setup_markets)


@pytest.fixture(scope="function")
def add_charging_station_assets_fresh_db(
    fresh_db: SQLAlchemy, setup_accounts_fresh_db, setup_markets_fresh_db
) -> dict[str, GenericAsset]:
    return create_charging_station_assets(
        fresh_db, setup_accounts_fresh_db, setup_markets_fresh_db
    )


def create_charging_station_assets(
    db: SQLAlchemy, setup_accounts, setup_markets
) -> dict[str, GenericAsset]:
    """Add uni- and bi-directional charging station assets, set their capacity value and their initial SOC."""
    oneway_evse = GenericAssetType(name="one-way_evse")
    twoway_evse = GenericAssetType(name="two-way_evse")

    charging_station = GenericAsset(
        name="Test charging station",
        owner=setup_accounts["Prosumer"],
        generic_asset_type=oneway_evse,
        latitude=10,
        longitude=100,
        attributes=dict(
            capacity_in_mw=2,
            max_soc_in_mwh=5,
            min_soc_in_mwh=0,
            soc_in_mwh=2.5,
            soc_datetime="2015-01-01T00:00+01",
            soc_udi_event_id=203,
            market_id=setup_markets["epex_da"].id,
            is_consumer=True,
            is_producer=False,
            can_curtail=True,
            can_shift=True,
        ),
    )
    charging_station_power_sensor = Sensor(
        name="power",
        generic_asset=charging_station,
        unit="MW",
        event_resolution=timedelta(minutes=15),
        attributes=dict(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        ),
    )
    db.session.add(charging_station_power_sensor)

    bidirectional_charging_station = GenericAsset(
        name="Test charging station (bidirectional)",
        owner=setup_accounts["Prosumer"],
        generic_asset_type=twoway_evse,
        latitude=10,
        longitude=100,
        attributes=dict(
            capacity_in_mw=2,
            max_soc_in_mwh=5,
            min_soc_in_mwh=0,
            soc_in_mwh=2.5,
            soc_datetime="2015-01-01T00:00+01",
            soc_udi_event_id=203,
            market_id=setup_markets["epex_da"].id,
            is_consumer=True,
            is_producer=True,
            can_curtail=True,
            can_shift=True,
        ),
    )
    bidirectional_charging_station_power_sensor = Sensor(
        name="power",
        generic_asset=bidirectional_charging_station,
        unit="MW",
        event_resolution=timedelta(minutes=15),
        attributes=dict(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        ),
    )
    db.session.add(bidirectional_charging_station_power_sensor)
    return {
        "Test charging station": charging_station,
        "Test charging station (bidirectional)": bidirectional_charging_station,
    }


@pytest.fixture(scope="module")
def add_assets_with_site_power_limits(
    db: SQLAlchemy, setup_accounts, setup_generic_asset_types
) -> dict[str, Sensor]:
    """
    Add two batteries with different site power constraints. The first defines a symmetric site-level power limit of 2 MW
    by setting the capacity_in_mw asset attribute. The second defines a 900 kW consumption limit and 750 kW production limit.
    In addition, the capacity_in_mw is also defined to check the fallback strategy.
    """
    battery_symmetric_site_power_limit = GenericAsset(
        name="Battery (with symmetric site limits)",
        owner=setup_accounts["Prosumer"],
        generic_asset_type=setup_generic_asset_types["battery"],
        attributes=dict(
            capacity_in_mw=2,
            max_soc_in_mwh=5,
            min_soc_in_mwh=0,
        ),
    )
    battery_symmetric_power_sensor = Sensor(
        name="power",
        generic_asset=battery_symmetric_site_power_limit,
        unit="MW",
    )

    battery_asymmetric_site_power_limit = GenericAsset(
        name="Battery (with asymmetric site limits)",
        owner=setup_accounts["Prosumer"],
        generic_asset_type=setup_generic_asset_types["battery"],
        attributes=dict(
            capacity_in_mw=2,
            consumption_capacity_in_mw=0.9,
            production_capacity_in_mw=0.75,
            max_soc_in_mwh=5,
            min_soc_in_mwh=0,
        ),
    )
    battery_asymmetric_power_sensor = Sensor(
        name="power",
        generic_asset=battery_asymmetric_site_power_limit,
        unit="MW",
    )

    db.session.add_all(
        [battery_symmetric_power_sensor, battery_asymmetric_power_sensor]
    )
    db.session.flush()
    return {
        "Battery (with symmetric site limits)": battery_symmetric_power_sensor,
        "Battery (with asymmetric site limits)": battery_asymmetric_power_sensor,
    }


@pytest.fixture(scope="module")
def add_weather_sensors(db, setup_generic_asset_types) -> dict[str, Sensor]:
    return create_weather_sensors(db, setup_generic_asset_types)


@pytest.fixture(scope="function")
def add_weather_sensors_fresh_db(
    fresh_db, setup_generic_asset_types_fresh_db
) -> dict[str, Sensor]:
    return create_weather_sensors(fresh_db, setup_generic_asset_types_fresh_db)


def create_weather_sensors(db: SQLAlchemy, generic_asset_types) -> dict[str, Sensor]:
    """Add a weather station asset with two weather sensors."""

    weather_station = GenericAsset(
        name="Test weather station",
        generic_asset_type=generic_asset_types["weather_station"],
        latitude=33.4843866,
        longitude=126,
    )
    db.session.add(weather_station)

    wind_sensor = Sensor(
        name="wind speed",
        generic_asset=weather_station,
        event_resolution=timedelta(minutes=5),
        unit="m/s",
    )
    db.session.add(wind_sensor)

    temp_sensor = Sensor(
        name="temperature",
        generic_asset=weather_station,
        event_resolution=timedelta(minutes=5),
        unit="°C",
    )
    db.session.add(temp_sensor)
    return {"wind": wind_sensor, "temperature": temp_sensor, "asset": weather_station}


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
    """Add a battery SOC sensor to the db."""
    return create_battery_soc_sensor(db, setup_generic_assets)


@pytest.fixture(scope="function")
def battery_soc_sensor_fresh_db(fresh_db: SQLAlchemy, setup_generic_assets_fresh_db):
    """Add a battery SOC sensor to the fresh db."""
    return create_battery_soc_sensor(fresh_db, setup_generic_assets_fresh_db)


def create_battery_soc_sensor(db: SQLAlchemy, setup_generic_assets):
    """Add a battery SOC sensor."""
    soc_sensor = Sensor(
        name="state of charge",
        unit="%",
        generic_asset=setup_generic_assets["test_battery"],
    )
    db.session.add(soc_sensor)
    return soc_sensor


@pytest.fixture
def run_as_cli(app, monkeypatch):
    """
    Use this to run your test as if it is run from the CLI.
    This is useful where some auth restrictions (e.g. for querying) are in place.
    FlexMeasures is more lenient with them if the CLI is running, as it considers
    the user a sysadmin.
    """
    monkeypatch.setitem(app.config, "PRETEND_RUNNING_AS_CLI", True)


@pytest.fixture(scope="function")
def clean_redis(app):
    failed = app.queues["forecasting"].failed_job_registry
    app.queues["forecasting"].empty()
    for job_id in failed.get_job_ids():
        failed.remove(app.queues["forecasting"].fetch_job(job_id))
    app.redis_connection.flushdb()


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


@pytest.fixture(scope="module")
def capacity_sensors(db, add_battery_assets, setup_sources):
    battery = add_battery_assets["Test battery with dynamic power capacity"]
    production_capacity_sensor = Sensor(
        name="production capacity",
        generic_asset=battery,
        unit="kW",
        event_resolution="PT15M",
        attributes={"consumption_is_positive": True},
    )
    consumption_capacity_sensor = Sensor(
        name="consumption capacity",
        generic_asset=battery,
        unit="kW",
        event_resolution="PT15M",
        attributes={"consumption_is_positive": True},
    )

    power_capacity_sensor = Sensor(
        name="power capacity",
        generic_asset=battery,
        unit="kW",
        event_resolution="PT15M",
        attributes={"consumption_is_positive": True},
    )

    site_power_capacity_sensor = Sensor(
        name="site power capacity",
        generic_asset=battery,
        unit="kW",
        event_resolution="PT15M",
        attributes={"consumption_is_positive": True},
    )

    db.session.add_all(
        [
            production_capacity_sensor,
            consumption_capacity_sensor,
            site_power_capacity_sensor,
        ]
    )
    db.session.flush()

    time_slots = pd.date_range(
        datetime(2015, 1, 2), datetime(2015, 1, 2, 7, 45), freq="15T"
    ).tz_localize("Europe/Amsterdam")

    add_beliefs(
        db=db,
        sensor=production_capacity_sensor,
        time_slots=time_slots,
        values=[200] * 4 * 4 + [300] * 4 * 4,
        source=setup_sources["Seita"],
    )

    add_beliefs(
        db=db,
        sensor=consumption_capacity_sensor,
        time_slots=time_slots,
        values=[250] * 4 * 4 + [150] * 4 * 4,
        source=setup_sources["Seita"],
    )

    add_beliefs(
        db=db,
        sensor=power_capacity_sensor,
        time_slots=time_slots,
        values=[225] * 4 * 4 + [199] * 4 * 4,
        source=setup_sources["Seita"],
    )

    add_beliefs(
        db=db,
        sensor=site_power_capacity_sensor,
        time_slots=time_slots,
        values=[1300] * 4 * 4 + [1050] * 4 * 4,
        source=setup_sources["Seita"],
    )

    db.session.commit()

    time_slots = pd.date_range(
        datetime(2016, 1, 2), datetime(2016, 1, 2, 7, 45), freq="15T"
    ).tz_localize("Europe/Amsterdam")
    values = [250] * 4 * 4 + [150] * 4 * 4
    beliefs = [
        TimedBelief(
            event_start=dt,
            event_value=val,
            sensor=production_capacity_sensor,
            source=setup_sources["DummySchedule"],
            belief_time="2015-01-02T00:00+01",
        )
        for dt, val in zip(time_slots, values)
    ]
    db.session.add_all(beliefs)
    db.session.commit()

    yield dict(
        production=production_capacity_sensor,
        consumption=consumption_capacity_sensor,
        power_capacity=power_capacity_sensor,
        site_power_capacity=site_power_capacity_sensor,
    )


@pytest.fixture(scope="module")
def soc_sensors(db, add_battery_assets, setup_sources) -> tuple:
    """Add battery sensors for instantaneous soc-maxima (in kWh), soc-maxima (in MWh) and soc-targets (in MWh).

    The SoC values on each sensor linearly increase from 0 to 5 MWh.
    """
    battery = add_battery_assets["Test battery with dynamic power capacity"]

    soc_maxima = Sensor(
        name="soc_maxima",
        generic_asset=battery,
        unit="kWh",
        event_resolution=timedelta(0),
    )

    soc_minima = Sensor(
        name="soc_minima",
        generic_asset=battery,
        unit="MWh",
        event_resolution=timedelta(0),
    )

    soc_targets = Sensor(
        name="soc_targets",
        generic_asset=battery,
        unit="MWh",
        event_resolution=timedelta(0),
    )

    db.session.add_all([soc_maxima, soc_minima, soc_targets])
    db.session.flush()

    time_slots = pd.date_range(
        datetime(2015, 1, 1, 2), datetime(2015, 1, 2), freq="15T"
    ).tz_localize("Europe/Amsterdam")

    values = np.arange(len(time_slots)) / (len(time_slots) - 1)
    values = values * 5

    add_beliefs(
        db=db,
        sensor=soc_maxima,
        time_slots=time_slots,
        values=values * 1000,  # MWh -> kWh
        source=setup_sources["Seita"],
    )

    add_beliefs(
        db=db,
        sensor=soc_minima,
        time_slots=time_slots,
        values=values,
        source=setup_sources["Seita"],
    )

    add_beliefs(
        db=db,
        sensor=soc_targets,
        time_slots=time_slots,
        values=values,
        source=setup_sources["Seita"],
    )

    yield soc_maxima, soc_minima, soc_targets, values


@pytest.fixture(scope="module")
def setup_multiple_sources(db, add_battery_assets):
    battery = add_battery_assets["Test battery with dynamic power capacity"]

    test_sensor = Sensor(
        name="test sensor",
        generic_asset=battery,
        unit="kW",
        event_resolution=timedelta(minutes=15),
    )

    s1 = DataSource(name="S1", type="type 1")
    s2 = DataSource(name="S2", type="type 2")
    s3 = DataSource(name="S3", type="type 3")

    db.session.add_all([s1, s2, s3, test_sensor])

    for s in [s1, s2]:
        add_beliefs(
            db=db,
            sensor=test_sensor,
            time_slots=[pd.Timestamp("2024-01-01T10:00:00+01:00")],
            values=[1],
            source=s,
        )

    add_beliefs(
        db=db,
        sensor=test_sensor,
        time_slots=[pd.Timestamp("2024-01-02T10:00:00+01:00")],
        values=[1],
        source=s3,
    )

    db.session.commit()

    return test_sensor, s1, s2, s3


def add_beliefs(
    db,
    sensor: Sensor,
    time_slots: pd.DatetimeIndex,
    values: list[int | float] | np.ndarray,
    source: DataSource,
):
    beliefs = [
        TimedBelief(
            event_start=dt,
            belief_horizon=parse_duration("PT0M"),
            event_value=val,
            sensor=sensor,
            source=source,
        )
        for dt, val in zip(time_slots, values)
    ]
    db.session.add_all(beliefs)


@pytest.fixture
def mock_get_status(mocker: MockerFixture):
    return mocker.patch("flexmeasures.data.services.sensors.get_status", autospec=True)
