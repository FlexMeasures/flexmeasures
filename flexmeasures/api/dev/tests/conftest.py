from datetime import timedelta

from flask_security import SQLAlchemySessionUserDatastore
import pytest

from flexmeasures.data.models.time_series import Sensor


@pytest.fixture(scope="function")
def setup_api_fresh_test_data(fresh_db, setup_roles_users_fresh_db):
    """
    Set up data for API dev tests.

    TODO: refactor if some tests can work without a fresh db
    """
    print("Setting up data for API dev tests on %s" % fresh_db.engine)

    from flexmeasures.data.models.user import User, Role

    user_datastore = SQLAlchemySessionUserDatastore(fresh_db.session, User, Role)

    gas_sensor = Sensor(
        name="some gas sensor",
        unit="m",
        event_resolution=timedelta(minutes=10),
    )
    fresh_db.session.add(gas_sensor)
    gas_sensor.owner = setup_roles_users_fresh_db["Test Supplier"]

    test_prosumer = user_datastore.find_user(email="test_prosumer@seita.nl")
    mdc_role = user_datastore.create_role(name="MDC", description="Meter Data Company")
    user_datastore.add_role_to_user(test_prosumer, mdc_role)
