from datetime import timedelta

import pytest

from flexmeasures.data.models.generic_assets import GenericAssetType, GenericAsset
from flexmeasures.data.models.time_series import Sensor


@pytest.fixture(scope="module")
def setup_api_test_data(db, setup_roles_users, setup_generic_assets):
    """
    Set up data for API dev tests.
    """
    print("Setting up data for API dev tests on %s" % db.engine)
    add_gas_sensor(db, setup_roles_users["Test Prosumer User 2"])


@pytest.fixture(scope="function")
def setup_api_fresh_test_data(
    fresh_db, setup_roles_users_fresh_db, setup_generic_assets_fresh_db
):
    """
    Set up fresh data for API dev tests.
    """
    print("Setting up fresh data for API dev tests on %s" % fresh_db.engine)
    for sensor in Sensor.query.all():
        fresh_db.delete(sensor)
    add_gas_sensor(fresh_db, setup_roles_users_fresh_db["Test Prosumer User 2"])


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
