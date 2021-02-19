from typing import List
from datetime import timedelta

import isodate
import pytest

from flask_security import SQLAlchemySessionUserDatastore
from flask_security.utils import hash_password

from flexmeasures.data.services.users import create_user


@pytest.fixture(scope="function", autouse=True)
def setup_api_test_data(db):
    """
    Set up data for API v1 tests.
    """
    print("Setting up data for API v1 tests on %s" % db.engine)

    from flexmeasures.data.models.user import User, Role
    from flexmeasures.data.models.assets import Asset, AssetType, Power
    from flexmeasures.data.models.data_sources import DataSource

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)

    # Create an anonymous user
    create_user(
        username="anonymous user with Prosumer role",
        email="demo@seita.nl",
        password=hash_password("testtest"),
        user_roles=[
            "Prosumer",
            dict(name="anonymous", description="Anonymous test user"),
        ],
    )

    # Create 1 test asset for the anonymous user
    test_prosumer = user_datastore.find_user(email="demo@seita.nl")
    test_asset_type = AssetType(name="test-type")
    db.session.add(test_asset_type)
    asset_names = ["CS 0"]
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

    # Create a test user without a USEF role
    create_user(
        username="test user without roles",
        email="test_user@seita.nl",
        password=hash_password("testtest"),
    )

    # Create 5 test assets for the test_prosumer user
    test_prosumer = user_datastore.find_user(email="test_prosumer@seita.nl")
    asset_names = ["CS 1", "CS 2", "CS 3", "CS 4", "CS 5"]
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
        if asset_name == "CS 4":
            asset.event_resolution = timedelta(hours=1)
        assets.append(asset)
        db.session.add(asset)

    # Add power forecasts to one of the assets, for two sources
    cs_5 = Asset.query.filter(Asset.name == "CS 5").one_or_none()
    test_supplier = user_datastore.find_user(email="test_supplier@seita.nl")
    prosumer_data_source = DataSource.query.filter(
        DataSource.user == test_prosumer
    ).one_or_none()
    supplier_data_source = DataSource.query.filter(
        DataSource.user == test_supplier
    ).one_or_none()
    meter_data = []
    for i in range(6):
        p_1 = Power(
            datetime=isodate.parse_datetime("2015-01-01T00:00:00Z")
            + timedelta(minutes=15 * i),
            horizon=timedelta(0),
            value=(100.0 + i) * -1,
            asset_id=cs_5.id,
            data_source_id=prosumer_data_source.id,
        )
        p_2 = Power(
            datetime=isodate.parse_datetime("2015-01-01T00:00:00Z")
            + timedelta(minutes=15 * i),
            horizon=timedelta(hours=0),
            value=(1000.0 - 10 * i) * -1,
            asset_id=cs_5.id,
            data_source_id=supplier_data_source.id,
        )
        meter_data.append(p_1)
        meter_data.append(p_2)
    db.session.bulk_save_objects(meter_data)

    print("Done setting up data for API v1 tests")
