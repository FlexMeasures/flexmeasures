from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask_security import SQLAlchemySessionUserDatastore, hash_password
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete, select

from flexmeasures import Sensor, Source, User, UserRole
from flexmeasures.auth.policy import ACCOUNT_READER_ROLE
from flexmeasures.data.models.automations import (
    Automation,
    AutomationRun,
    AutomationRunAttempt,
    AutomationRunJob,
)
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import TimedBelief

# 10-minute resolution values for "some gas sensor"
GAS_MEASUREMENTS_10MIN = [91.3, 91.7, 92.1]


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


@pytest.fixture(scope="module")
def setup_supplier_account_reader(db, setup_api_test_data, setup_roles_users) -> User:
    """Set up a reader in the account that owns the API test gas sensor."""
    datastore = SQLAlchemySessionUserDatastore(db.session, User, UserRole)
    role = datastore.find_role(ACCOUNT_READER_ROLE) or datastore.create_role(
        name=ACCOUNT_READER_ROLE
    )
    reader = datastore.create_user(
        username="Test Supplier Account Reader",
        email="test_supplier_reader@seita.nl",
        password=hash_password("testtest"),
        account_id=db.session.get(
            User, setup_roles_users["Test Supplier User"]
        ).account_id,
        roles=[role],
    )
    db.session.add(DataSource(user=reader))
    db.session.commit()
    return reader


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
    add_inactive_users(db, setup_accounts)


@pytest.fixture(scope="function")
def setup_inactive_user_fresh_db(
    fresh_db, setup_accounts_fresh_db, setup_roles_users_fresh_db
):
    """
    Set up one inactive user and one inactive admin.
    """
    add_inactive_users(fresh_db, setup_accounts_fresh_db)


def add_inactive_users(db, setup_accounts):
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
    event_values = list(values) if values else GAS_MEASUREMENTS_10MIN
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


@pytest.fixture(scope="module")
def add_automations(db, add_battery_assets) -> list[Automation]:
    return create_test_automations(db, add_battery_assets["Test battery"])


@pytest.fixture(scope="function")
def add_automations_fresh_db(fresh_db, add_battery_assets_fresh_db) -> list[Automation]:
    return create_test_automations(
        fresh_db, add_battery_assets_fresh_db["Test battery"]
    )


def create_test_automations(db, battery: GenericAsset) -> list[Automation]:
    """Two forecasting automations on the battery, with runs, attempts and jobs that show the outcomes an operator must tell apart."""
    generator = DataSource(
        name="automations API test generator",
        type="forecaster",
        model="TrainPredictPipeline",
    )
    automations = [
        Automation(
            asset_id=battery.id,
            generator=generator,
            type="forecasting",
            name="Day-ahead forecasts",
            cronstr="0 6 * * *",
            timezone="Europe/Amsterdam",
            cursor=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
            active=True,
            parameters={"sensor": battery.sensors[0].id},
        ),
        Automation(
            asset_id=battery.id,
            generator=generator,
            type="forecasting",
            name="Intraday forecasts",
            cronstr="0 * * * *",
            timezone="UTC",
            cursor=datetime(2026, 7, 11, 5, 0, tzinfo=timezone.utc),
            active=False,
            parameters={"sensor": battery.sensors[0].id},
        ),
    ]
    db.session.add_all(automations)
    db.session.flush()
    run = AutomationRun(
        automation=automations[0],
        scheduled_at=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
        schedule_revision=automations[0].schedule_revision,
        automation_type="forecasting",
        generator_id=generator.id,
        dispatch_state="partially_queued",
        execution_state="pending",
        attempt_count=2,
        first_enqueued_at=datetime(2026, 7, 11, 4, 1, tzinfo=timezone.utc),
        parameters=dict(automations[0].parameters),
        plan={"cronstr": automations[0].cronstr, "timezone": automations[0].timezone},
        last_error_type="ConnectionError",
        last_error_message="lost Redis connection",
    )
    db.session.add(run)
    db.session.flush()
    db.session.add_all(
        [
            AutomationRunJob(
                run=run,
                logical_job_key="cycle-001",
                rq_job_id=f"automation-run-{run.id}-cycle-001",
                queue="forecasting",
                kind="forecast-cycle",
                status="queued",
                depends_on=[],
                payload={},
            ),
            AutomationRunJob(
                run=run,
                logical_job_key="wrap-up",
                rq_job_id=f"automation-run-{run.id}-wrap-up",
                queue="forecasting",
                kind="forecast-wrap-up",
                status="pending",
                depends_on=["cycle-001"],
                payload={},
            ),
        ]
    )
    # The second automation shows the other two outcomes an operator needs to tell apart:
    # an occurrence which failed before queueing anything, and one which queued and then ran to completion.
    failed_before_queueing = AutomationRun(
        automation=automations[1],
        scheduled_at=datetime(2026, 7, 11, 5, 0, tzinfo=timezone.utc),
        schedule_revision=automations[1].schedule_revision,
        automation_type="forecasting",
        generator_id=generator.id,
        dispatch_state="failed",
        execution_state="pending",
        attempt_count=1,
        parameters=dict(automations[1].parameters),
        plan={"cronstr": automations[1].cronstr, "timezone": automations[1].timezone},
        last_error_type="ValidationError",
        last_error_message="forecast output sensor no longer exists",
    )
    fully_queued_and_succeeded = AutomationRun(
        automation=automations[1],
        scheduled_at=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
        schedule_revision=automations[1].schedule_revision,
        automation_type="forecasting",
        generator_id=generator.id,
        dispatch_state="queued",
        execution_state="succeeded",
        attempt_count=2,
        first_enqueued_at=datetime(2026, 7, 11, 4, 1, tzinfo=timezone.utc),
        dispatch_completed_at=datetime(2026, 7, 11, 4, 2, tzinfo=timezone.utc),
        execution_started_at=datetime(2026, 7, 11, 4, 3, tzinfo=timezone.utc),
        execution_completed_at=datetime(2026, 7, 11, 4, 9, tzinfo=timezone.utc),
        parameters=dict(automations[1].parameters),
        plan={"cronstr": automations[1].cronstr, "timezone": automations[1].timezone},
    )
    db.session.add_all([failed_before_queueing, fully_queued_and_succeeded])
    db.session.flush()
    db.session.add_all(
        [
            AutomationRunAttempt(
                run=failed_before_queueing,
                attempt_no=1,
                owner="runner-a:1",
                started_at=datetime(2026, 7, 11, 5, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 7, 11, 5, 0, tzinfo=timezone.utc),
                outcome="failed",
                queued_job_count=0,
                error_type="ValidationError",
                error_message="forecast output sensor no longer exists",
            ),
            AutomationRunAttempt(
                run=fully_queued_and_succeeded,
                attempt_no=1,
                owner="runner-a:1",
                started_at=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
                outcome="failed",
                queued_job_count=0,
                error_type="ConnectionError",
                error_message="lost Redis connection",
            ),
            AutomationRunAttempt(
                run=fully_queued_and_succeeded,
                attempt_no=2,
                owner="runner-b:2",
                started_at=datetime(2026, 7, 11, 4, 1, tzinfo=timezone.utc),
                finished_at=datetime(2026, 7, 11, 4, 2, tzinfo=timezone.utc),
                outcome="queued",
                queued_job_count=1,
            ),
            AutomationRunJob(
                run=fully_queued_and_succeeded,
                logical_job_key="cycle-001",
                rq_job_id=f"automation-run-{fully_queued_and_succeeded.id}-cycle-001",
                queue="forecasting",
                kind="forecast-cycle",
                status="succeeded",
                depends_on=[],
                payload={},
                enqueued_at=datetime(2026, 7, 11, 4, 1, tzinfo=timezone.utc),
                started_at=datetime(2026, 7, 11, 4, 3, tzinfo=timezone.utc),
                finished_at=datetime(2026, 7, 11, 4, 9, tzinfo=timezone.utc),
            ),
        ]
    )
    db.session.commit()
    return automations


def create_report_sensors(db, battery, accounts, generic_asset_types) -> dict:
    """Create report sensors inside and outside the target asset subtree."""
    input_1 = Sensor(
        "report input 1",
        generic_asset=battery,
        event_resolution=timedelta(hours=1),
        unit="kW",
    )
    input_2 = Sensor(
        "report input 2",
        generic_asset=battery,
        event_resolution=timedelta(hours=1),
        unit="kW",
    )
    output = Sensor(
        "report output",
        generic_asset=battery,
        event_resolution=timedelta(hours=2),
        unit="kW",
    )
    cost_output = Sensor(
        "cost output",
        generic_asset=battery,
        event_resolution=timedelta(hours=2),
        unit="EUR",
    )
    local_price = Sensor(
        "local price",
        generic_asset=battery,
        event_resolution=timedelta(hours=1),
        unit="EUR/kWh",
    )
    sibling = GenericAsset(
        name="Sibling battery",
        generic_asset_type=generic_asset_types["battery"],
        owner=battery.owner,
        parent_asset=battery.parent_asset,
    )
    sibling_output = Sensor(
        "sibling output", generic_asset=sibling, event_resolution=timedelta(hours=2)
    )
    foreign = GenericAsset(
        name="Foreign report asset",
        generic_asset_type=generic_asset_types["battery"],
        owner=accounts["Dummy"],
    )
    foreign_input = Sensor(
        "foreign input",
        generic_asset=foreign,
        event_resolution=timedelta(hours=1),
        unit="kW",
    )
    foreign_price = Sensor(
        "foreign price",
        generic_asset=foreign,
        event_resolution=timedelta(hours=1),
        unit="EUR/kWh",
    )
    db.session.add_all(
        [
            input_1,
            input_2,
            output,
            cost_output,
            local_price,
            sibling,
            sibling_output,
            foreign,
            foreign_input,
            foreign_price,
        ]
    )
    db.session.commit()
    return {
        "asset": battery,
        "input_1": input_1,
        "input_2": input_2,
        "output": output,
        "cost_output": cost_output,
        "local_price": local_price,
        "sibling_output": sibling_output,
        "foreign_input": foreign_input,
        "foreign_price": foreign_price,
    }


@pytest.fixture(scope="module")
def setup_report_sensors(
    db, add_battery_assets, setup_accounts, setup_generic_asset_types
):
    return create_report_sensors(
        db,
        add_battery_assets["Test battery"],
        setup_accounts,
        setup_generic_asset_types,
    )


@pytest.fixture(scope="function")
def setup_report_sensors_fresh_db(
    fresh_db,
    add_battery_assets_fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
):
    return create_report_sensors(
        fresh_db,
        add_battery_assets_fresh_db["Test battery"],
        setup_accounts_fresh_db,
        setup_generic_asset_types_fresh_db,
    )
