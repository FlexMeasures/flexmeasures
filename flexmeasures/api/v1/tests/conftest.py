from typing import List
from datetime import timedelta

import isodate
import pytest

from flask_security.utils import hash_password

from flexmeasures.data.services.users import create_user


@pytest.fixture(scope="module", autouse=True)
def setup_api_test_data(db, setup_accounts, setup_roles_users, add_market_prices):
    """
    Set up data for API v1 tests.
    """
    print("Setting up data for API v1 tests on %s" % db.engine)

    from flexmeasures.data.models.assets import Asset, AssetType, Power
    from flexmeasures.data.models.data_sources import DataSource

    # Create an anonymous user TODO: used for demo purposes, maybe "demo-user" would be a better name
    test_anonymous_user = create_user(
        username="anonymous user",
        email="demo@seita.nl",
        password=hash_password("testtest"),
        account_name=setup_accounts["Dummy"].name,
        user_roles=[
            dict(name="anonymous", description="Anonymous test user"),
        ],
    )

    # Create 1 test asset for the anonymous user
    test_asset_type = AssetType(name="test-type")
    db.session.add(test_asset_type)
    asset_names = ["CS 0"]
    assets: List[Asset] = []
    for asset_name in asset_names:
        asset = Asset(
            name=asset_name,
            owner_id=test_anonymous_user.id,
            asset_type_name="test-type",
            event_resolution=timedelta(minutes=15),
            capacity_in_mw=1,
            latitude=100,
            longitude=100,
            unit="MW",
        )
        assets.append(asset)
        db.session.add(asset)

    """
    # Create a test user without a USEF role
    create_user(
        username="test user without roles",
        email="test_prosumer_user@seita.nl",
        password=hash_password("testtest"),
        account_name=setup_accounts["Prosumer"].name,
    )
    """

    # Create 5 test assets for the test user
    test_user = setup_roles_users["Test Prosumer User"]
    asset_names = ["CS 1", "CS 2", "CS 3", "CS 4", "CS 5"]
    assets: List[Asset] = []
    for asset_name in asset_names:
        asset = Asset(
            name=asset_name,
            owner_id=test_user.id,
            asset_type_name="test-type",
            event_resolution=timedelta(minutes=15)
            if not asset_name == "CS 4"
            else timedelta(hours=1),
            capacity_in_mw=1,
            latitude=100,
            longitude=100,
            unit="MW",
        )
        assets.append(asset)
        db.session.add(asset)

    # Add power forecasts to one of the assets, for two sources
    cs_5 = Asset.query.filter(Asset.name == "CS 5").one_or_none()
    user1_data_source = DataSource.query.filter(
        DataSource.user == test_user
    ).one_or_none()
    test_user_2 = setup_roles_users["Test Prosumer User 2"]
    user2_data_source = DataSource.query.filter(
        DataSource.user == test_user_2
    ).one_or_none()
    meter_data = []
    for i in range(6):
        p_1 = Power(
            datetime=isodate.parse_datetime("2015-01-01T00:00:00Z")
            + timedelta(minutes=15 * i),
            horizon=timedelta(0),
            value=(100.0 + i) * -1,
            sensor_id=cs_5.id,
            data_source_id=user1_data_source.id,
        )
        p_2 = Power(
            datetime=isodate.parse_datetime("2015-01-01T00:00:00Z")
            + timedelta(minutes=15 * i),
            horizon=timedelta(hours=0),
            value=(1000.0 - 10 * i) * -1,
            sensor_id=cs_5.id,
            data_source_id=user2_data_source.id,
        )
        meter_data.append(p_1)
        meter_data.append(p_2)
    db.session.bulk_save_objects(meter_data)

    print("Done setting up data for API v1 tests")


@pytest.fixture(scope="function")
def setup_fresh_api_test_data(fresh_db, setup_roles_users_fresh_db):
    db = fresh_db
    setup_roles_users = setup_roles_users_fresh_db
    from flexmeasures.data.models.assets import Asset, AssetType

    # Create 5 test assets for the test_prosumer user
    test_user = setup_roles_users["Test Prosumer User"]
    test_asset_type = AssetType(name="test-type")
    db.session.add(test_asset_type)
    asset_names = ["CS 1", "CS 2", "CS 3", "CS 4", "CS 5"]
    assets: List[Asset] = []
    for asset_name in asset_names:
        asset = Asset(
            name=asset_name,
            owner_id=test_user.id,
            asset_type_name="test-type",
            event_resolution=timedelta(minutes=15)
            if not asset_name == "CS 4"
            else timedelta(hours=1),
            capacity_in_mw=1,
            latitude=100,
            longitude=100,
            unit="MW",
        )
        assets.append(asset)
        db.session.add(asset)
