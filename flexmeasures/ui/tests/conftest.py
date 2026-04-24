import pytest

from flexmeasures.data.services.users import create_user
from flexmeasures.ui.tests.utils import login, logout
from flexmeasures import Asset
from flexmeasures.data.models.generic_assets import GenericAsset


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


@pytest.fixture(scope="function")
def as_prosumer_account_admin(client):
    """Login the prosumer account-admin (has the 'account-admin' role)."""
    login(client, "test_prosumer_user_2@seita.nl", "testtest")
    yield
    logout(client)


@pytest.fixture(scope="function")
def as_dummy_account_admin(client):
    """Login the dummy account-admin (account-admin of a different account)."""
    login(client, "test_dummy_account_admin@seita.nl", "testtest")
    yield
    logout(client)


@pytest.fixture
def public_asset(db, setup_generic_asset_types):
    """A public asset with no owner account, readable by any logged-in user."""
    asset = GenericAsset(
        name="public-test-asset",
        generic_asset_type=setup_generic_asset_types["battery"],
        latitude=10,
        longitude=100,
    )
    db.session.add(asset)
    db.session.commit()
    return asset


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


@pytest.fixture
def assets_prosumer(db, setup_accounts, setup_generic_asset_types):
    assets = []
    for name in ["TestAsset", "TestAsset2"]:
        asset = Asset(
            name=name,
            generic_asset_type=setup_generic_asset_types["battery"],
            owner=setup_accounts["Prosumer"],
            latitude=70.4,
            longitude=30.9,
        )
        assets.append(asset)

    db.session.add_all(assets)

    return assets
