from datetime import timedelta

import pytest

from flexmeasures.data.models.user import Account, User
from flexmeasures.data.models.generic_assets import GenericAssetType, GenericAsset
from flexmeasures.data.models.time_series import Sensor


@pytest.fixture(scope="module", autouse=True)
def setup_api_test_data(db, setup_roles_users):
    """
    Set up data for API dev tests.
    """
    print("Setting up data for API v2.0 tests on %s" % db.engine)
    add_gas_sensor(db, setup_roles_users["Test User 2"])
    move_user2_to_supplier()


@pytest.fixture(scope="function")
def setup_api_fresh_test_data(fresh_db, setup_roles_users_fresh_db):
    """
    Set up fresh data for API dev tests.
    """
    print("Setting up fresh data for API dev tests on %s" % fresh_db.engine)
    for sensor in Sensor.query.all():
        fresh_db.delete(sensor)
    add_gas_sensor(fresh_db, setup_roles_users_fresh_db["Test User 2"])
    move_user2_to_supplier()


def add_gas_sensor(db, test_supplier):
    incineration_type = GenericAssetType(
        name="waste incinerator",
    )
    db.session.add(incineration_type)
    db.session.flush()
    incineration_asset = GenericAsset(
        name="incineration line",
        generic_asset_type=incineration_type,
        account_id=test_supplier.account_id,
    )
    db.session.add(incineration_asset)
    db.session.flush()
    gas_sensor = Sensor(
        name="some gas sensor",
        unit="m³/h",
        event_resolution=timedelta(minutes=10),
        generic_asset=incineration_asset,
    )
    db.session.add(gas_sensor)
    gas_sensor.owner = test_supplier


def move_user2_to_supplier():
    """
    move the user 2 to the supplier account
    """
    supplier_account = Account.query.filter(
        Account.name == "Test Supplier Account"
    ).one_or_none()
    user2 = User.query.filter(User.email == "test_user_2@seita.nl").one_or_none()
    user2.account = supplier_account
