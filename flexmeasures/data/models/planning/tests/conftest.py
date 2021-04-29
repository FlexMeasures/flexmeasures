import pytest


@pytest.fixture(scope="function", autouse=True)
def setup_planning_test_data(db, add_market_prices):
    """
    Set up data for all planning tests.
    """
    print("Setting up data for planning tests on %s" % db.engine)
