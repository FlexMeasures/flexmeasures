import pytest
from sqlalchemy import select

from flexmeasures import User
from flexmeasures.api.v3_0.tests.conftest import add_incineration_line
from flexmeasures.data.models.time_series import Sensor


@pytest.fixture(scope="module")
def setup_api_test_data(db, setup_roles_users, setup_generic_assets):
    """
    Set up data for API dev tests.
    """
    print("Setting up data for API dev tests on %s" % db.engine)
    add_incineration_line(
        db, db.session.get(User, setup_roles_users["Test Supplier User"])
    )


@pytest.fixture(scope="function")
def setup_api_fresh_test_data(
    fresh_db, setup_roles_users_fresh_db, setup_generic_assets_fresh_db
):
    """
    Set up fresh data for API dev tests.
    """
    print("Setting up fresh data for API dev tests on %s" % fresh_db.engine)
    for sensor in fresh_db.session.scalars(select(Sensor)).all():
        fresh_db.delete(sensor)
    add_incineration_line(
        fresh_db,
        fresh_db.session.get(User, setup_roles_users_fresh_db["Test Supplier User"]),
    )
