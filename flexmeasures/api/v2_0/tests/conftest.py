from flask_security import SQLAlchemySessionUserDatastore
from flask_security.utils import hash_password
import pytest


@pytest.fixture(scope="module", autouse=True)
def setup_api_test_data(db, setup_roles_users, add_market_prices, add_battery_assets):
    """
    Set up data for API v2.0 tests.
    """
    print("Setting up data for API v2.0 tests on %s" % db.engine)

    from flexmeasures.data.models.user import User, Role

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)

    battery = add_battery_assets["Test battery"]
    battery.owner = setup_roles_users["Test Supplier"]

    test_prosumer = user_datastore.find_user(email="test_prosumer@seita.nl")
    admin_role = user_datastore.create_role(name="admin", description="God powers")
    user_datastore.add_role_to_user(test_prosumer, admin_role)


@pytest.fixture(scope="module")
def setup_inactive_user(db, setup_account, setup_roles_users):
    """
    Set up one inactive user.
    """
    from flexmeasures.data.models.user import User, Role

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    user_datastore.create_user(
        username="inactive test user",
        email="inactive@seita.nl",
        password=hash_password("testtest"),
        account_id=setup_account.id,
        active=False,
    )
