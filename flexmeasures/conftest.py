import pytest
from random import random
from datetime import datetime, timedelta

from isodate import parse_duration
import pandas as pd
import numpy as np
from flask import request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_security import roles_accepted, SQLAlchemySessionUserDatastore
from flask_security.utils import hash_password
from werkzeug.exceptions import (
    InternalServerError,
    BadRequest,
    Unauthorized,
    Forbidden,
    Gone,
)

from flexmeasures.app import create as create_app
from flexmeasures.utils.time_utils import as_server_time
from flexmeasures.data.services.users import create_user, find_user_by_email
from flexmeasures.data.models.assets import AssetType, Asset, Power
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.markets import Market, Price


"""
Useful things for all tests.

One application is made per test session, but cleanup and recreation currently happens per test.
This can be sped up if needed by moving some functions to "module" or even "session" scope,
but then the tests need to share data and and data modifications can lead to tricky debugging.
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


@pytest.fixture(scope="function")
def db(app):
    """
    Provide a db object with the structure freshly created. This assumes a clean database.
    It does clean up after itself when it's done (drops everything).
    """
    print("DB FIXTURE")
    # app is an instance of a flask app, _db a SQLAlchemy DB
    from flexmeasures.data.config import db as _db

    _db.app = app
    with app.app_context():
        _db.create_all()

    yield _db

    print("DB FIXTURE CLEANUP")
    # Explicitly close DB connection
    _db.session.close()

    _db.drop_all()


@pytest.fixture(scope="function")
def setup_roles_users(db):
    """Create a minimal set of roles and users"""
    create_user(
        username="Test Prosumer",
        email="test_prosumer@seita.nl",
        password=hash_password("testtest"),
        user_roles=dict(name="Prosumer", description="A Prosumer with a few assets."),
    )
    create_user(
        username="Test Supplier",
        email="test_supplier@seita.nl",
        password=hash_password("testtest"),
        user_roles=dict(name="Supplier", description="A Supplier trading on markets."),
    )


@pytest.fixture(scope="function", autouse=True)
def setup_markets(db):
    """Create the epex_da market."""
    from flexmeasures.data.models.markets import Market, MarketType

    day_ahead = MarketType(
        name="day_ahead",
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=True,
    )
    db.session.add(day_ahead)
    epex_da = Market(
        name="epex_da",
        market_type=day_ahead,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
        knowledge_horizon_fnc="x_days_ago_at_y_oclock",
        knowledge_horizon_par={"x": 1, "y": 12, "z": "Europe/Paris"},
    )
    db.session.add(epex_da)


@pytest.fixture(scope="function", autouse=True)
def setup_assets(db, setup_roles_users, setup_markets):
    """Make some asset types and add assets to known test users."""

    data_source = DataSource(name="Seita", type="demo script")
    db.session.add(data_source)

    db.session.add(
        AssetType(
            name="solar",
            is_producer=True,
            can_curtail=True,
            daily_seasonality=True,
            yearly_seasonality=True,
        )
    )
    db.session.add(
        AssetType(
            name="wind",
            is_producer=True,
            can_curtail=True,
            daily_seasonality=True,
            yearly_seasonality=True,
        )
    )

    test_prosumer = find_user_by_email("test_prosumer@seita.nl")
    test_market = Market.query.filter_by(name="epex_da").one_or_none()

    for asset_name in ["wind-asset-1", "wind-asset-2", "solar-asset-1"]:
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
            market_id=test_market.id,
        )
        asset.owner = test_prosumer
        db.session.add(asset)

        # one day of test data (one complete sine curve)
        time_slots = pd.date_range(
            datetime(2015, 1, 1), datetime(2015, 1, 1, 23, 45), freq="15T"
        )
        values = [random() * (1 + np.sin(x / 15)) for x in range(len(time_slots))]
        for dt, val in zip(time_slots, values):
            p = Power(
                datetime=as_server_time(dt),
                horizon=parse_duration("PT0M"),
                value=val,
                data_source_id=data_source.id,
            )
            p.asset = asset
            db.session.add(p)


@pytest.fixture(scope="function", autouse=True)
def add_market_prices(db: SQLAlchemy, setup_assets, setup_markets):
    """Add one day of market prices for the EPEX day-ahead market."""
    epex_da = Market.query.filter(Market.name == "epex_da").one_or_none()
    data_source = DataSource.query.filter_by(
        name="Seita", type="demo script"
    ).one_or_none()

    # one day of test data (one complete sine curve)
    time_slots = pd.date_range(
        datetime(2015, 1, 1), datetime(2015, 1, 2), freq="15T", closed="left"
    )
    values = [random() * (1 + np.sin(x / 15)) for x in range(len(time_slots))]
    for dt, val in zip(time_slots, values):
        p = Price(
            datetime=as_server_time(dt),
            horizon=timedelta(hours=0),
            value=val,
            data_source_id=data_source.id,
        )
        p.market = epex_da
        db.session.add(p)

    # another day of test data (8 expensive hours, 8 cheap hours, and again 8 expensive hours)
    time_slots = pd.date_range(
        datetime(2015, 1, 2), datetime(2015, 1, 3), freq="15T", closed="left"
    )
    values = [100] * 8 * 4 + [90] * 8 * 4 + [100] * 8 * 4
    for dt, val in zip(time_slots, values):
        p = Price(
            datetime=as_server_time(dt),
            horizon=timedelta(hours=0),
            value=val,
            data_source_id=data_source.id,
        )
        p.market = epex_da
        db.session.add(p)


@pytest.fixture(scope="function", autouse=True)
def add_battery_assets(db: SQLAlchemy, setup_roles_users, setup_markets):
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

    from flexmeasures.data.models.user import User, Role

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    test_prosumer = user_datastore.find_user(email="test_prosumer@seita.nl")
    epex_da = Market.query.filter(Market.name == "epex_da").one_or_none()

    battery = Asset(
        name="Test battery",
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
        market_id=epex_da.id,
        unit="MW",
    )
    battery.owner = test_prosumer
    db.session.add(battery)

    battery = Asset(
        name="Test battery with no known prices",
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
        market_id=epex_da.id,
        unit="MW",
    )
    battery.owner = test_prosumer
    db.session.add(battery)


@pytest.fixture(scope="function", autouse=True)
def add_charging_station_assets(db: SQLAlchemy, setup_roles_users, setup_markets):
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

    from flexmeasures.data.models.user import User, Role

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    test_prosumer = user_datastore.find_user(email="test_prosumer@seita.nl")
    epex_da = Market.query.filter(Market.name == "epex_da").one_or_none()

    charging_station = Asset(
        name="Test charging station",
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
        market_id=epex_da.id,
        unit="MW",
    )
    charging_station.owner = test_prosumer
    db.session.add(charging_station)

    bidirectional_charging_station = Asset(
        name="Test charging station (bidirectional)",
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
        market_id=epex_da.id,
        unit="MW",
    )
    bidirectional_charging_station.owner = test_prosumer
    db.session.add(bidirectional_charging_station)


@pytest.fixture(scope="function", autouse=True)
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
    @roles_accepted("admin")
    def vips_only():
        return jsonify({"message": "Nothing bad happened."}), 200
