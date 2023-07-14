import pytest

from flexmeasures.data.services.users import create_user
from flexmeasures.ui.tests.utils import login, logout


@pytest.fixture(scope="function")
def as_prosumer_user1(client):
    """
    Login the default test prosumer and log him out afterwards.
    """
    login(client, "test_prosumer_user@seita.nl", "testtest")
    yield
    logout(client)


@pytest.fixture(scope="function")
def as_admin(client):
    """
    Login the admin user and log him out afterwards.
    """
    login(client, "flexmeasures-admin@seita.nl", "testtest")
    yield
    logout(client)


@pytest.fixture(scope="module", autouse=True)
def setup_ui_test_data(
    db,
    setup_accounts,
    setup_roles_users,
    setup_markets,
    setup_sources,
    setup_generic_asset_types,
):
    """Create an admin."""
    create_user(
        username="Site Admin",
        email="flexmeasures-admin@seita.nl",
        password="testtest",
        account_name=setup_accounts["Prosumer"].name,
        user_roles=dict(name="admin", description="A site admin."),
    )
