from flask_security import SQLAlchemySessionUserDatastore
import pytest


@pytest.fixture(scope="function", autouse=True)
def setup_api_test_data(db, add_battery_assets):
    """
    Set up data for API v1.3 tests.
    """
    print("Setting up data for API v1.3 tests on %s" % db.engine)
