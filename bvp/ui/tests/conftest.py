import pytest

from flask_security.utils import hash_password

from bvp.data.services.users import create_user
from bvp.data.models.assets import Asset
from bvp.ui.tests.utils import login, logout


@pytest.fixture(scope="function")
def as_prosumer(client):
    """
    Login the default test prosumer and log him out afterwards.
    """
    login(client, "test_prosumer@seita.nl", "testtest")
    yield
    logout(client)


@pytest.fixture(scope="function")
def as_admin(client):
    """
    Login the admin user and log him out afterwards.
    """
    login(client, "bvp-admin@seita.nl", "testtest")
    yield
    logout(client)


@pytest.fixture(scope="function", autouse=True)
def setup_ui_test_data(db):
    """
    Create another prosumer, without data, and an admin
    """
    print("Setting up data for UI tests on %s" % db.engine)

    create_user(
        username="Site Admin",
        email="bvp-admin@seita.nl",
        password=hash_password("testtest"),
        user_roles=dict(name="admin", description="A site admin."),
    )

    test_prosumer2 = create_user(
        username="Second Test Prosumer",
        email="test_prosumer2@seita.nl",
        password=hash_password("testtest"),
        user_roles=dict(
            name="Prosumer", description="A Prosumer with one asset but no data."
        ),
    )
    asset = Asset(
        name="solar pane 1",
        display_name="Solar Pane 1",
        asset_type_name="solar",
        capacity_in_mw=10,
        latitude=10,
        longitude=100,
    )
    db.session.add(asset)
    asset.owner = test_prosumer2

    print("Done setting up data for UI tests")
