import pytest

from flask_security.utils import hash_password

from flexmeasures.data.services.users import create_user
from flexmeasures.data.models.assets import Asset
from flexmeasures.data.models.weather import WeatherSensor, WeatherSensorType
from flexmeasures.ui.tests.utils import login, logout


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
    login(client, "flexmeasures-admin@seita.nl", "testtest")
    yield
    logout(client)


@pytest.fixture(scope="function", autouse=True)
def setup_ui_test_data(db):
    """
    Create another prosumer, without data, and an admin
    Also, a weather sensor (and sensor type).
    """
    print("Setting up data for UI tests on %s" % db.engine)

    create_user(
        username="Site Admin",
        email="flexmeasures-admin@seita.nl",
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
        unit="MW",
        capacity_in_mw=10,
        latitude=10,
        longitude=100,
        min_soc_in_mwh=0,
        max_soc_in_mwh=0,
        soc_in_mwh=0,
    )
    db.session.add(asset)
    asset.owner = test_prosumer2

    # Create 1 weather sensor
    test_sensor_type = WeatherSensorType(name="radiation")
    db.session.add(test_sensor_type)
    sensor = WeatherSensor(
        name="radiation_sensor",
        weather_sensor_type_name="radiation",
        latitude=33.4843866,
        longitude=126,
        unit="kW/m²",
    )
    db.session.add(sensor)

    print("Done setting up data for UI tests")
