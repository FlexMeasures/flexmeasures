from typing import List
import pytest
from datetime import timedelta

import isodate
from flask_security import SQLAlchemySessionUserDatastore
from flask_security.utils import hash_password

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief


@pytest.fixture(scope="module")
def setup_api_test_data(db, setup_accounts, setup_roles_users, add_market_prices):
    """
    Set up data for API v1.1 tests.
    """
    print("Setting up data for API v1.1 tests on %s" % db.engine)

    from flexmeasures.data.models.user import User, Role
    from flexmeasures.data.models.assets import Asset, AssetType

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)

    # Create a user without proper registration as a data source
    user_datastore.create_user(
        username="test user with improper registration",
        email="test_improper_user@seita.nl",
        password=hash_password("testtest"),
        account_id=setup_accounts["Prosumer"].id,
    )

    # Create 3 test assets for the test_user
    test_user = setup_roles_users["Test Prosumer User"]
    test_asset_type = AssetType(name="test-type")
    db.session.add(test_asset_type)
    asset_names = ["CS 1", "CS 2", "CS 3"]
    assets: List[Asset] = []
    for asset_name in asset_names:
        asset = Asset(
            name=asset_name,
            owner_id=test_user.id,
            asset_type_name="test-type",
            event_resolution=timedelta(minutes=15),
            capacity_in_mw=1,
            latitude=100,
            longitude=100,
            unit="MW",
        )
        assets.append(asset)
        db.session.add(asset)

    # Add power forecasts to the assets
    cs_1 = Asset.query.filter(Asset.name == "CS 1").one_or_none()
    cs_2 = Asset.query.filter(Asset.name == "CS 2").one_or_none()
    cs_3 = Asset.query.filter(Asset.name == "CS 3").one_or_none()
    data_source = DataSource.query.filter(DataSource.user == test_user).one_or_none()
    cs1_beliefs = [
        TimedBelief(
            event_start=isodate.parse_datetime("2015-01-01T00:00:00Z")
            + timedelta(minutes=15 * i),
            belief_horizon=timedelta(hours=6),
            event_value=(300 + i) * -1,
            sensor=cs_1.corresponding_sensor,
            source=data_source,
        )
        for i in range(6)
    ]
    cs2_beliefs = [
        TimedBelief(
            event_start=isodate.parse_datetime("2015-01-01T00:00:00Z")
            + timedelta(minutes=15 * i),
            belief_horizon=timedelta(hours=6),
            event_value=(300 - i) * -1,
            sensor=cs_2.corresponding_sensor,
            source=data_source,
        )
        for i in range(6)
    ]
    cs3_beliefs = [
        TimedBelief(
            event_start=isodate.parse_datetime("2015-01-01T00:00:00Z")
            + timedelta(minutes=15 * i),
            belief_horizon=timedelta(hours=6),
            event_value=(0 + i) * -1,
            sensor=cs_3.corresponding_sensor,
            source=data_source,
        )
        for i in range(6)
    ]
    db.session.add_all(cs1_beliefs + cs2_beliefs + cs3_beliefs)

    print("Done setting up data for API v1.1 tests")


@pytest.fixture(scope="function")
def setup_fresh_api_v1_1_test_data(
    fresh_db, setup_roles_users_fresh_db, setup_markets_fresh_db
):
    return fresh_db
