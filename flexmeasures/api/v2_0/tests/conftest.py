from flask_security import SQLAlchemySessionUserDatastore
import pytest


@pytest.fixture(scope="function", autouse=True)
def setup_api_test_data(db):
    """
    Set up data for API v2.0 tests.
    """
    print("Setting up data for API v2.0 tests on %s" % db.engine)

    from flexmeasures.data.models.user import User, Role
    from flexmeasures.data.models.assets import Asset

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)

    test_supplier = user_datastore.find_user(email="test_supplier@seita.nl")
    battery = Asset.query.filter(Asset.name == "test_battery").one_or_none()
    battery.owner = test_supplier

    test_prosumer = user_datastore.find_user(email="test_prosumer@seita.nl")
    admin_role = user_datastore.create_role(name="admin", description="God powers")
    user_datastore.add_role_to_user(test_prosumer, admin_role)
