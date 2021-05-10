import pytest


@pytest.fixture(scope="module", autouse=True)
def setup_api_test_data(db, add_market_prices, add_battery_assets):
    """
    Set up data for API v1.2 tests.
    """
    print("Setting up data for API v1.2 tests on %s" % db.engine)
