import pytest

from flexmeasures.api.v3_0.tests.conftest import add_gas_sensor
from flexmeasures.data.models.time_series import Sensor


@pytest.fixture(scope="module")
def setup_api_test_data(db, setup_roles_users, setup_generic_assets):
    """
    Set up data for API dev tests.
    """
    print("Setting up data for API dev tests on %s" % db.engine)
    add_gas_sensor(db, setup_roles_users["Test Supplier User"])


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
    add_gas_sensor(fresh_db, setup_roles_users_fresh_db["Test Supplier User"])
