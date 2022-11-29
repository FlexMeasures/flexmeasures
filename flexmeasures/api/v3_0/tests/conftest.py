from datetime import timedelta

import pandas as pd
import pytest
from flask_security import SQLAlchemySessionUserDatastore, hash_password

from flexmeasures import Sensor, Source
from flexmeasures.data.models.generic_assets import GenericAssetType, GenericAsset
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.utils import get_data_source


@pytest.fixture(scope="module")
def setup_api_test_data(
    db, setup_roles_users, setup_generic_assets
) -> dict[str, Sensor]:
    """
    Set up data for API v3.0 tests.
    """
    print("Setting up data for API v3.0 tests on %s" % db.engine)
    gas_sensor = add_gas_sensor(db, setup_roles_users["Test Supplier User"])
    add_gas_measurements(
        db, setup_roles_users["Test Supplier User"].data_source[0], gas_sensor
    )
    return {gas_sensor.name: gas_sensor}


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
    add_gas_sensor(fresh_db, setup_roles_users_fresh_db["Test Supplier User"])


@pytest.fixture(scope="module")
def setup_inactive_user(db, setup_accounts, setup_roles_users):
    """
    Set up one inactive user.
    """
    from flexmeasures.data.models.user import User, Role

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    user_datastore.create_user(
        username="inactive test user",
        email="inactive@seita.nl",
        password=hash_password("testtest"),
        account_id=setup_accounts["Prosumer"].id,
        active=False,
    )


def add_gas_sensor(db, test_supplier_user) -> Sensor:
    incineration_type = GenericAssetType(
        name="waste incinerator",
    )
    db.session.add(incineration_type)
    db.session.flush()
    incineration_asset = GenericAsset(
        name="incineration line",
        generic_asset_type=incineration_type,
        account_id=test_supplier_user.account_id,
    )
    db.session.add(incineration_asset)
    gas_sensor = Sensor(
        name="some gas sensor",
        unit="m³/h",
        event_resolution=timedelta(minutes=10),
        generic_asset=incineration_asset,
    )
    db.session.add(gas_sensor)
    gas_sensor.owner = test_supplier_user.account
    db.session.flush()  # assign sensor id
    return gas_sensor


def add_gas_measurements(db, source: Source, gas_sensor: Sensor):
    event_starts = [
        pd.Timestamp("2021-08-02T00:00:00+02:00") + timedelta(minutes=minutes)
        for minutes in range(0, 30, 10)
    ]
    event_values = [91.3, 91.7, 92.1]
    beliefs = [
        TimedBelief(
            sensor=gas_sensor,
            source=source,
            event_start=event_start,
            belief_horizon=timedelta(0),
            event_value=event_value,
        )
        for event_start, event_value in zip(event_starts, event_values)
    ]
    db.session.add_all(beliefs)
