import pytest

from flask_security.utils import hash_password
from datetime import datetime
from isodate import parse_duration
import pandas as pd
import numpy as np
from random import random

from bvp.app import create as create_app
from bvp.data.services.users import create_user, find_user_by_email
from bvp.data.models.assets import AssetType, Asset, Power
from bvp.data.models.data_sources import DataSource

"""
Useful things for all tests.

One application is made per test session, but cleanup and recreation currently happens per test.
This can be sped up if needed by moving some functions to "module" or even "session" scope,
but then the tests need to share data and and data modifcations can lead to tricky debugging.
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
    from bvp.data.config import db as _db

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
    from bvp.data.models.markets import Market, MarketType

    day_ahead = MarketType(
        name="day_ahead",
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=True,
    )
    db.session.add(day_ahead)
    epex_da = Market(name="epex_da", market_type=day_ahead)
    db.session.add(epex_da)


@pytest.fixture(scope="function", autouse=True)
def setup_assets(db, setup_roles_users):
    """Make some asset types and add assets to known test users."""

    data_source = DataSource(
        label="data entered for demonstration purposes", type="script", user_id=None
    )
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

    for asset_name in ["wind-asset-1", "wind-asset-2", "solar-asset-1"]:
        asset = Asset(
            name=asset_name,
            asset_type_name="wind" if "wind" in asset_name else "solar",
            capacity_in_mw=1,
            latitude=100,
            longitude=100,
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
                datetime=dt,
                horizon=parse_duration("-PT15M"),
                value=val,
                data_source_id=data_source.id,
            )
            p.asset = asset
            db.session.add(p)
