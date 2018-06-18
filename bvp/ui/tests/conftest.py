import pytest

from flask_security import SQLAlchemySessionUserDatastore

from bvp.ui.tests.utils import login, logout


@pytest.fixture(scope="function")
def use_auth(client):
    """
    Login an asset owner and log him out afterwards.
    This requires certain populated data of course, so there might come a redesign here.
    """
    login(client, "test_prosumer@seita.nl", "testtest")

    yield

    logout(client)


@pytest.fixture(scope="function", autouse=True)
def setup_ui_test_data(db):
    """
    Create an asset for the prosumer, so the pages load (even without data in graphs, for now).
    """
    print("Setting up data for UI tests on %s" % db.engine)

    from bvp.data.models.user import User, Role
    from bvp.data.models.assets import Asset

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    test_prosumer = user_datastore.find_user(email="test_prosumer@seita.nl")
    asset = Asset(
        name="solar pane 1",
        display_name="Solar Pane 1",
        asset_type_name="solar",
        capacity_in_mw=10,
        latitude=100,
        longitude=100,
    )
    db.session.add(asset)
    asset.owner = test_prosumer

    print("Done setting up data for UI tests")
