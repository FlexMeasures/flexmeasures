import pytest


@pytest.fixture(scope="module", autouse=True)
def setup_api_test_data(db, add_market_prices, add_battery_assets):
    """
    Set up data for API v1.3 tests.
    """
    print("Setting up data for API v1.3 tests on %s" % db.engine)


@pytest.fixture(scope="function")
def setup_fresh_api_test_data(fresh_db, add_battery_assets_fresh_db):
    """
    Set up data for API v1.3 tests.
    """
    pass
