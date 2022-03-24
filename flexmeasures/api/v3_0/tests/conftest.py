from datetime import timedelta

import pytest
from flask_security import SQLAlchemySessionUserDatastore, hash_password

from flexmeasures.data.models.generic_assets import GenericAssetType, GenericAsset
from flexmeasures.data.models.time_series import Sensor


@pytest.fixture(scope="module")
def setup_api_test_data(db, setup_roles_users, setup_generic_assets):
    """
    Set up data for API v3.0 tests.
    """
    print("Setting up data for API v3.0 tests on %s" % db.engine)
    add_gas_sensor(db, setup_roles_users["Test Supplier User"])


@pytest.fixture(scope="function")
def setup_api_fresh_test_data(
    fresh_db, setup_roles_users_fresh_db, setup_generic_assets_fresh_db
):
    """
    Set up fresh data for API dev tests.
    """
    print("Setting up fresh data for API 3.0 tests on %s" % fresh_db.engine)
    for sensor in Sensor.query.all():
        fresh_db.delete(sensor)
    add_gas_sensor(fresh_db, setup_roles_users_fresh_db["Test Supplier User"])


@pytest.fixture(scope="module")
def setup_inactive_user(db, setup_accounts, setup_roles_users):
    """
    Set up one inactive user.
    """
    from flexmeasures.data.models.user import User, Role

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    user_datastore.create_user(
        username="inactive test user",
        email="inactive@seita.nl",
        password=hash_password("testtest"),
        account_id=setup_accounts["Prosumer"].id,
        active=False,
    )


def add_gas_sensor(db, test_supplier_user):
    incineration_type = GenericAssetType(
        name="waste incinerator",
    )
    db.session.add(incineration_type)
    db.session.flush()
    incineration_asset = GenericAsset(
        name="incineration line",
        generic_asset_type=incineration_type,
        account_id=test_supplier_user.account_id,
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
    gas_sensor.owner = test_supplier_user.account
