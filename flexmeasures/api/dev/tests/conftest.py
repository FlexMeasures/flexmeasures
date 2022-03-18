import pytest


@pytest.fixture(scope="module")
def setup_api_test_data(db, setup_roles_users, setup_generic_assets):
    """
    Set up data for API dev tests.
    """
    print("Setting up data for API dev tests on %s" % db.engine)


@pytest.fixture(scope="function")
def setup_api_fresh_test_data(
    fresh_db, setup_roles_users_fresh_db, setup_generic_assets_fresh_db
):
    """
    Set up fresh data for API dev tests.
    """
    print("Setting up fresh data for API dev tests on %s" % fresh_db.engine)
