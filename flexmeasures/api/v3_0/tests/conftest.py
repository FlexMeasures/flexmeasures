from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from flask_security import SQLAlchemySessionUserDatastore, hash_password
from sqlalchemy import select, delete

from flexmeasures import Sensor, Source, User, UserRole
from flexmeasures.data.models.data_sources import DataSource
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
        db, db.session.get(User, setup_roles_users["Test Supplier User"])
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
    for sensor in fresh_db.session.scalars(select(Sensor)).all():
        fresh_db.session.execute(delete(Sensor).filter_by(id=sensor.id))
    sensors = add_incineration_line(
        fresh_db,
        fresh_db.session.get(User, setup_roles_users_fresh_db["Test Supplier User"]),
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


@pytest.fixture(scope="module")
def add_asset_with_children(db, setup_roles_users):
    test_supplier_user = setup_roles_users["Test Supplier User"]
    parent_type = GenericAssetType(
        name="parent",
    )
    child_type = GenericAssetType(name="child")

    db.session.add_all([parent_type, child_type])

    parent = GenericAsset(
        name="parent",
        generic_asset_type=parent_type,
        account_id=test_supplier_user,
    )
    db.session.add(parent)
    db.session.flush()  # assign parent asset id

    assets = [
        GenericAsset(
            name=f"child_{i}",
            generic_asset_type=child_type,
            parent_asset_id=parent.id,
            account_id=test_supplier_user,
        )
        for i in range(1, 3)
    ]

    db.session.add_all(assets)
    db.session.flush()  # assign children asset ids

    assets.append(parent)

    return {a.name: a for a in assets}


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
    other_source = DataSource(name="Other source", type="demo script")
    db.session.add(other_source)
    db.session.flush()
    add_gas_measurements(db, other_source, gas_sensor, values=[91.3, np.nan, 92.1])

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

    empty_temperature_sensor = Sensor(
        name="empty temperature sensor",
        unit="°C",
        event_resolution=timedelta(0),
        generic_asset=incineration_asset,
    )
    db.session.add(empty_temperature_sensor)

    db.session.flush()  # assign sensor ids
    return {
        gas_sensor.name: gas_sensor,
        temperature_sensor.name: temperature_sensor,
        empty_temperature_sensor.name: empty_temperature_sensor,
    }


def add_gas_measurements(db, source: Source, sensor: Sensor, values=None):
    event_starts = [
        pd.Timestamp("2021-05-02T00:00:00+02:00") + timedelta(minutes=minutes)
        for minutes in range(0, 30, 10)
    ]
    event_values = list(values) if values else [91.3, 91.7, 92.1]
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
