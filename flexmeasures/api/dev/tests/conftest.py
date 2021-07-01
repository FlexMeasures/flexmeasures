from datetime import timedelta

from flask_security import SQLAlchemySessionUserDatastore
import pytest

from flexmeasures.data.models.time_series import Sensor


@pytest.fixture(scope="module", autouse=True)
def setup_api_test_data(db, setup_roles_users):
    """
    Set up data for API dev tests.
    """
    print("Setting up data for API v2.0 tests on %s" % db.engine)
    give_prosumer_the_MDC_role(db)


@pytest.fixture(scope="function")
def setup_api_fresh_test_data(fresh_db, setup_roles_users_fresh_db):
    """
    Set up fresh data for API dev tests.
    """
    print("Setting up data for API dev tests on %s" % fresh_db.engine)

    gas_sensor = Sensor(
        name="some gas sensor",
        unit="m³/h",
        event_resolution=timedelta(minutes=10),
    )
    fresh_db.session.add(gas_sensor)
    gas_sensor.owner = setup_roles_users_fresh_db["Test Supplier"]

    give_prosumer_the_MDC_role(fresh_db)


def give_prosumer_the_MDC_role(db):

    from flexmeasures.data.models.user import User, Role

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    test_prosumer = user_datastore.find_user(email="test_prosumer@seita.nl")
    mdc_role = user_datastore.create_role(name="MDC", description="Meter Data Company")
    user_datastore.add_role_to_user(test_prosumer, mdc_role)
