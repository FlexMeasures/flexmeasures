import pytest


@pytest.fixture(scope="module", autouse=True)
def setup_api_test_data(db, setup_roles_users, add_market_prices, add_battery_assets):
    """
    Set up data for API v2.0 tests.
    """
    print("Setting up data for API v2.0 tests on %s" % db.engine)

    # Add battery asset
    battery = add_battery_assets["Test battery"]
    battery.owner = setup_roles_users["Test Prosumer User 2"]
