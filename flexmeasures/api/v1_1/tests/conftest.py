from typing import List
import pytest
from datetime import timedelta

import isodate
from flask_security import SQLAlchemySessionUserDatastore
from flask_security.utils import hash_password

from flexmeasures.data.models.assets import Power
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.services.users import create_user


@pytest.fixture(scope="module")
def setup_api_test_data(db, setup_account, setup_roles_users, add_market_prices):
    """
    Set up data for API v1.1 tests.
    """
    print("Setting up data for API v1.1 tests on %s" % db.engine)

    from flexmeasures.data.models.user import User, Role
    from flexmeasures.data.models.assets import Asset, AssetType

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)

    # Create a user without proper registration as a data source
    user = user_datastore.create_user(
        username="test user with improper registration",
        email="test_improper_user@seita.nl",
        password=hash_password("testtest"),
        account_id=setup_account.id,
    )
    role = user_datastore.find_role("Prosumer")
    user_datastore.add_role_to_user(user, role)

    # Create a test user without a USEF role
    create_user(
        username="test user without roles",
        email="test_user@seita.nl",
        password=hash_password("testtest"),
        account_name=setup_account.name,
    )

    # Create 3 test assets for the test_prosumer user
    test_prosumer = setup_roles_users["Test Prosumer"]
    test_asset_type = AssetType(name="test-type")
    db.session.add(test_asset_type)
    asset_names = ["CS 1", "CS 2", "CS 3"]
    assets: List[Asset] = []
    for asset_name in asset_names:
        asset = Asset(
            name=asset_name,
            asset_type_name="test-type",
            event_resolution=timedelta(minutes=15),
            capacity_in_mw=1,
            latitude=100,
            longitude=100,
            unit="MW",
        )
        asset.owner = test_prosumer
        assets.append(asset)
        db.session.add(asset)

    # Add power forecasts to the assets
    cs_1 = Asset.query.filter(Asset.name == "CS 1").one_or_none()
    cs_2 = Asset.query.filter(Asset.name == "CS 2").one_or_none()
    cs_3 = Asset.query.filter(Asset.name == "CS 3").one_or_none()
    data_source = DataSource.query.filter(
        DataSource.user == test_prosumer
    ).one_or_none()
    power_forecasts = []
    for i in range(6):
        p_1 = Power(
            datetime=isodate.parse_datetime("2015-01-01T00:00:00Z")
            + timedelta(minutes=15 * i),
            horizon=timedelta(hours=6),
            value=(300 + i) * -1,
            asset_id=cs_1.id,
            data_source_id=data_source.id,
        )
        p_2 = Power(
            datetime=isodate.parse_datetime("2015-01-01T00:00:00Z")
            + timedelta(minutes=15 * i),
            horizon=timedelta(hours=6),
            value=(300 - i) * -1,
            asset_id=cs_2.id,
            data_source_id=data_source.id,
        )
        p_3 = Power(
            datetime=isodate.parse_datetime("2015-01-01T00:00:00Z")
            + timedelta(minutes=15 * i),
            horizon=timedelta(hours=6),
            value=(0 + i) * -1,
            asset_id=cs_3.id,
            data_source_id=data_source.id,
        )
        power_forecasts.append(p_1)
        power_forecasts.append(p_2)
        power_forecasts.append(p_3)
    db.session.bulk_save_objects(power_forecasts)

    print("Done setting up data for API v1.1 tests")


@pytest.fixture(scope="function")
def setup_fresh_api_v1_1_test_data(
    fresh_db, setup_roles_users_fresh_db, setup_markets_fresh_db
):
    return fresh_db
