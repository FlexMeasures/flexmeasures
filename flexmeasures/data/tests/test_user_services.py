import pytest
from sqlalchemy import select, func

from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import User, Role
from flexmeasures.data.services.users import (
    create_user,
    find_user_by_email,
    delete_user,
    InvalidFlexMeasuresUser,
)
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief


def test_create_user(
    fresh_db, setup_accounts_fresh_db, setup_roles_users_fresh_db, app
):
    """Create a user"""
    num_users = fresh_db.session.scalar(select(func.count()).select_from(User))
    prosumer_account = setup_accounts_fresh_db["Prosumer"]
    user = create_user(
        email="new_user@seita.nl",
        password="testtest",
        account_name=prosumer_account.name,
        user_roles=["SomeRole"],
    )
    assert (
        fresh_db.session.scalar(select(func.count()).select_from(User)) == num_users + 1
    )
    assert user.email == "new_user@seita.nl"
    assert user.username == "new_user"
    assert user.account.name == "Test Prosumer Account"
    assert user.roles == [
        fresh_db.session.execute(
            select(Role).filter_by(name="SomeRole")
        ).scalar_one_or_none()
    ]
    assert fresh_db.session.execute(
        select(DataSource).filter_by(user_id=user.id)
    ).scalar_one_or_none()
    assert fresh_db.session.execute(
        select(DataSource).filter_by(name=user.username)
    ).scalar_one_or_none()

    user_audit_log = (
        fresh_db.session.query(AuditLog)
        .filter_by(affected_user_id=user.id)
        .one_or_none()
    )
    assert user_audit_log.event == "User new_user created"
    assert user_audit_log.affected_account_id == prosumer_account.id
    assert user_audit_log.active_user_id is None


def test_create_user_no_account(
    fresh_db, setup_accounts_fresh_db, setup_roles_users_fresh_db, app
):
    """Create a user where the account still needs creation, test for both audit log entries"""
    user = create_user(
        email="new_user@seita.nl",
        password="testtest",
        account_name="new_account",
        user_roles=["SomeRole"],
    )

    user_audit_log = (
        fresh_db.session.query(AuditLog)
        .filter_by(event="User new_user created")
        .one_or_none()
    )
    assert user_audit_log.affected_user_id == user.id
    assert user_audit_log.affected_account_id == user.account_id

    account_audit_log = (
        fresh_db.session.query(AuditLog)
        .filter_by(event="Account new_account created")
        .one_or_none()
    )
    assert account_audit_log.affected_user_id is None
    assert account_audit_log.affected_account_id == user.account_id
    assert account_audit_log.active_user_id is None


def test_create_invalid_user(
    fresh_db, setup_accounts_fresh_db, setup_roles_users_fresh_db, app
):
    """A few invalid attempts to create a user"""
    with pytest.raises(InvalidFlexMeasuresUser) as exc_info:
        create_user(password="testtest")
    assert "No email" in str(exc_info.value)
    with pytest.raises(InvalidFlexMeasuresUser) as exc_info:
        create_user(
            email="test_user_AT_seita.nl",
            password="testtest",
            account_name=setup_accounts_fresh_db["Prosumer"].name,
        )
        assert "not a valid" in str(exc_info.value)
    """ # This check is disabled during testing, as testing should work without internet and be fast
    with pytest.raises(InvalidFlexMeasuresUser) as exc_info:
        create_user(
            email="test_prosumer@sdkkhflzsxlgjxhglkzxjhfglkxhzlzxcvlzxvb.nl",
            password="testtest",
            account_name=setup_account_fresh_db.name,
        )
    assert "not seem to be deliverable" in str(exc_info.value)
    """
    with pytest.raises(InvalidFlexMeasuresUser) as exc_info:
        create_user(
            email="test_prosumer_user@seita.nl",
            password="testtest",
            account_name=setup_accounts_fresh_db["Prosumer"].name,
        )
    assert "already exists" in str(exc_info.value)
    with pytest.raises(InvalidFlexMeasuresUser) as exc_info:
        create_user(
            email="new_user@seita.nl",
            username="Test Prosumer User",
            password="testtest",
            account_name=setup_accounts_fresh_db["Prosumer"].name,
        )
    assert "already exists" in str(exc_info.value)
    with pytest.raises(InvalidFlexMeasuresUser) as exc_info:
        create_user(
            email="new_user@seita.nl",
            username="New Test Prosumer User",
            password="testtest",
        )
    assert "without knowing the name of the account" in str(exc_info.value)


def test_delete_user(fresh_db, setup_roles_users_fresh_db, setup_assets_fresh_db, app):
    """Check that deleting a user does not lead to deleting their organisation's (asset/sensor/beliefs) data.
    Also check that an audit log entry is created + old audit log entries get affected_user_id set to None.
    """
    prosumer: User = find_user_by_email("test_prosumer_user@seita.nl")
    prosumer_account_id = prosumer.account_id
    num_users_before = fresh_db.session.scalar(select(func.count(User.id)))

    # Find assets belonging to the user's organisation
    asset_query = select(GenericAsset).filter_by(account_id=prosumer_account_id)
    assets_before = fresh_db.session.scalars(asset_query).all()
    assert (
        len(assets_before) > 0
    ), "Test assets should have been set up, otherwise we'd not be testing whether they're kept."

    # Find all the organisation's sensors
    sensors_before = []
    for asset in assets_before:
        sensors_before.extend(asset.sensors)

    # Count all the organisation's beliefs
    beliefs_query = select(func.count()).filter(
        TimedBelief.sensor_id.in_([sensor.id for sensor in sensors_before])
    )
    num_beliefs_before = fresh_db.session.scalar(beliefs_query)
    assert (
        num_beliefs_before > 0
    ), "Some beliefs should have been set up, otherwise we'd not be testing whether they're kept."

    # Add creation audit log record
    user_creation_audit_log = AuditLog(
        event="User Test Prosumer User created test",
        affected_user_id=prosumer.id,
        affected_account_id=prosumer_account_id,
    )
    fresh_db.session.add(user_creation_audit_log)

    # Delete the user
    delete_user(prosumer)
    assert find_user_by_email("test_prosumer_user@seita.nl") is None
    assert fresh_db.session.scalar(select(func.count(User.id))) == num_users_before - 1

    # Check whether the organisation's assets, sensors and beliefs were kept
    assets_after = fresh_db.session.scalars(asset_query).all()
    assert assets_after == assets_before

    num_beliefs_after = fresh_db.session.scalar(beliefs_query)
    assert num_beliefs_after == num_beliefs_before

    user_deletion_audit_log = (
        fresh_db.session.query(AuditLog)
        .filter_by(event="User Test Prosumer User deleted")
        .one_or_none()
    )
    assert user_deletion_audit_log.affected_user_id is None
    assert user_deletion_audit_log.affected_account_id == prosumer_account_id
    assert user_deletion_audit_log.active_user_id is None

    fresh_db.session.refresh(user_creation_audit_log)
    assert user_creation_audit_log.affected_user_id is None
