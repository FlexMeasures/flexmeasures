import pytest
from datetime import timedelta

from flask_security import SQLAlchemySessionUserDatastore, hash_password

from flexmeasures import Sensor, User, UserRole
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType


@pytest.fixture(scope="module")
def dummy_accounts(db, app):
    dummy_account_1 = Account(name="dummy account 1")
    db.session.add(dummy_account_1)

    dummy_account_2 = Account(name="dummy account 2")
    db.session.add(dummy_account_2)

    # Assign account IDs
    db.session.flush()

    return {
        dummy_account_1.name: dummy_account_1,
        dummy_account_2.name: dummy_account_2,
    }


@pytest.fixture(scope="module")
def dummy_user(db, app, dummy_accounts):
    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, UserRole)
    user = user_datastore.create_user(
        username="dummy user",
        email="dummy_user@seita.nl",
        password=hash_password("testtest"),
        account_id=dummy_accounts["dummy account 1"].id,
        active=True,
    )
    return user


@pytest.fixture(scope="module")
def dummy_assets(db, app, dummy_accounts):
    dummy_asset_type = GenericAssetType(name="DummyGenericAssetType")
    db.session.add(dummy_asset_type)

    dummy_asset_1 = GenericAsset(
        name="dummy asset 1",
        generic_asset_type=dummy_asset_type,
        owner=dummy_accounts["dummy account 1"],
    )
    db.session.add(dummy_asset_1)

    dummy_asset_2 = GenericAsset(
        name="dummy asset 2",
        generic_asset_type=dummy_asset_type,
        owner=dummy_accounts["dummy account 1"],
    )
    db.session.add(dummy_asset_2)

    dummy_asset_3 = GenericAsset(
        name="dummy asset 3",
        generic_asset_type=dummy_asset_type,
        owner=dummy_accounts["dummy account 2"],
    )
    db.session.add(dummy_asset_3)

    return {
        dummy_asset_1.name: dummy_asset_1,
        dummy_asset_2.name: dummy_asset_2,
        dummy_asset_3.name: dummy_asset_3,
    }


@pytest.fixture(scope="module")
def setup_dummy_sensors(db, app, dummy_assets):
    dummy_asset = dummy_assets["dummy asset 1"]
    sensor1 = Sensor(
        "sensor 1",
        generic_asset=dummy_asset,
        event_resolution=timedelta(hours=1),
        unit="MWh",
    )
    db.session.add(sensor1)

    sensor2 = Sensor(
        "sensor 2",
        generic_asset=dummy_asset,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
    )
    db.session.add(sensor2)

    sensor3 = Sensor(
        "sensor 3",
        generic_asset=dummy_asset,
        event_resolution=timedelta(hours=1),
        unit="EUR",
    )
    db.session.add(sensor3)

    sensor4 = Sensor(
        "sensor 4",
        generic_asset=dummy_asset,
        event_resolution=timedelta(hours=1),
        unit="MW",
    )
    db.session.add(sensor4)

    db.session.commit()

    yield sensor1, sensor2


@pytest.fixture(scope="module")
def setup_efficiency_sensors(db, app, dummy_assets):
    dummy_asset = dummy_assets["dummy asset 1"]
    sensor = Sensor(
        "efficiency",
        generic_asset=dummy_asset,
        event_resolution=timedelta(hours=1),
        unit="%",
    )
    db.session.add(sensor)
    db.session.commit()

    return sensor


@pytest.fixture(scope="module")
def setup_site_capacity_sensor(db, app, dummy_assets, setup_sources):
    dummy_asset = dummy_assets["dummy asset 1"]
    sensor = Sensor(
        "site-power-capacity",
        generic_asset=dummy_asset,
        event_resolution="P1Y",
        unit="MVA",
    )
    db.session.add(sensor)
    capacity = TimedBelief(
        sensor=sensor,
        source=setup_sources["Seita"],
        event_value=0.8,
        belief_horizon="P45D",
        event_start="2024-02-26T00:00+02",
    )
    db.session.add(capacity)

    db.session.commit()

    return {sensor.name: sensor}
