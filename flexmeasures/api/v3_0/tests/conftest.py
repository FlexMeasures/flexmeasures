from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest
from flask_security import SQLAlchemySessionUserDatastore, hash_password

from flexmeasures import Sensor, Source, User, UserRole
from flexmeasures.data.models.generic_assets import GenericAssetType, GenericAsset
from flexmeasures.data.models.time_series import TimedBelief


@pytest.fixture(scope="module")
def setup_api_test_data(
    db, setup_roles_users, setup_generic_assets
) -> dict[str, Sensor]:
    """
    Set up data for API v3.0 tests.
    """
    print("Setting up data for API v3.0 tests on %s" % db.engine)
    sensors = add_incineration_line(
        db, User.query.get(setup_roles_users["Test Supplier User"])
    )
    return sensors


@pytest.fixture(scope="function")
def setup_api_fresh_test_data(
    fresh_db, setup_roles_users_fresh_db, setup_generic_assets_fresh_db
):
    """
    Set up fresh data for API dev tests.
    """
    print("Setting up fresh data for API 3.0 tests on %s" % fresh_db.engine)
    for sensor in Sensor.query.all():
        fresh_db.delete(sensor)
    sensors = add_incineration_line(
        fresh_db, User.query.get(setup_roles_users_fresh_db["Test Supplier User"])
    )
    return sensors


@pytest.fixture(scope="module")
def setup_inactive_user(db, setup_accounts, setup_roles_users):
    """
    Set up one inactive user and one inactive admin.
    """
    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, UserRole)
    user_datastore.create_user(
        username="inactive test user",
        email="inactive_user@seita.nl",
        password=hash_password("testtest"),
        account_id=setup_accounts["Prosumer"].id,
        active=False,
    )
    admin = user_datastore.create_user(
        username="inactive test admin",
        email="inactive_admin@seita.nl",
        password=hash_password("testtest"),
        account_id=setup_accounts["Prosumer"].id,
        active=False,
    )
    role = user_datastore.find_role("admin")
    user_datastore.add_role_to_user(admin, role)


@pytest.fixture(scope="function")
def setup_user_without_data_source(
    fresh_db, setup_accounts_fresh_db, setup_roles_users_fresh_db
) -> User:
    """
    Set up one user directly without setting up a corresponding data source.
    """

    user_datastore = SQLAlchemySessionUserDatastore(fresh_db.session, User, UserRole)
    user = user_datastore.create_user(
        username="test admin with improper registration as a data source",
        email="improper_user@seita.nl",
        password=hash_password("testtest"),
        account_id=setup_accounts_fresh_db["Prosumer"].id,
        active=True,
    )
    role = user_datastore.find_role("admin")
    user_datastore.add_role_to_user(user, role)
    return user


@pytest.fixture(scope="function")
def keep_scheduling_queue_empty(app):
    app.queues["scheduling"].empty()
    yield
    app.queues["scheduling"].empty()


def add_incineration_line(db, test_supplier_user) -> dict[str, Sensor]:
    incineration_type = GenericAssetType(
        name="waste incinerator",
    )
    db.session.add(incineration_type)
    incineration_asset = GenericAsset(
        name="incineration line",
        generic_asset_type=incineration_type,
        owner=test_supplier_user.account,
    )
    db.session.add(incineration_asset)
    gas_sensor = Sensor(
        name="some gas sensor",
        unit="m³/h",
        event_resolution=timedelta(minutes=10),
        generic_asset=incineration_asset,
    )
    db.session.add(gas_sensor)
    add_gas_measurements(db, test_supplier_user.data_source[0], gas_sensor)
    temperature_sensor = Sensor(
        name="some temperature sensor",
        unit="°C",
        event_resolution=timedelta(0),
        generic_asset=incineration_asset,
    )
    db.session.add(temperature_sensor)
    add_temperature_measurements(
        db, test_supplier_user.data_source[0], temperature_sensor
    )

    db.session.flush()  # assign sensor ids
    return {gas_sensor.name: gas_sensor, temperature_sensor.name: temperature_sensor}


def add_gas_measurements(db, source: Source, sensor: Sensor):
    event_starts = [
        pd.Timestamp("2021-05-02T00:00:00+02:00") + timedelta(minutes=minutes)
        for minutes in range(0, 30, 10)
    ]
    event_values = [91.3, 91.7, 92.1]
    beliefs = [
        TimedBelief(
            sensor=sensor,
            source=source,
            event_start=event_start,
            belief_horizon=timedelta(0),
            event_value=event_value,
        )
        for event_start, event_value in zip(event_starts, event_values)
    ]
    db.session.add_all(beliefs)


def add_temperature_measurements(db, source: Source, sensor: Sensor):
    event_starts = [
        pd.Timestamp("2021-05-02T00:00:00+02:00") + timedelta(minutes=minutes)
        for minutes in range(0, 30, 10)
    ]
    event_values = [815, 817, 818]
    beliefs = [
        TimedBelief(
            sensor=sensor,
            source=source,
            event_start=event_start,
            belief_horizon=timedelta(0),
            event_value=event_value,
        )
        for event_start, event_value in zip(event_starts, event_values)
    ]
    db.session.add_all(beliefs)
