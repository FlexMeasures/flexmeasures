import pytest

# from bvp.data.services.users import find_user_by_email


@pytest.fixture(scope="function", autouse=True)
def setup_test_data(db):
    """
    """
    print("Setting up data for data tests on %s" % db.engine)
    # test_prosumer = find_user_by_email("test_prosumer@seita.nl")
    print("Done setting up data for data tests")
