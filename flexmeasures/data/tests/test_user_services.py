import pytest

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
    num_users = User.query.count()
    user = create_user(
        email="new_user@seita.nl",
        password="testtest",
        account_name=setup_accounts_fresh_db["Prosumer"].name,
        user_roles=["SomeRole"],
    )
    assert User.query.count() == num_users + 1
    assert user.email == "new_user@seita.nl"
    assert user.username == "new_user"
    assert user.account.name == "Test Prosumer Account"
    assert user.roles == [Role.query.filter_by(name="SomeRole").one_or_none()]
    assert DataSource.query.filter_by(user_id=user.id).one_or_none()
    assert DataSource.query.filter_by(name=user.username).one_or_none()


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
    """Check that deleting a user does not lead to deleting their organisation's (asset/sensor/beliefs) data."""
    prosumer: User = find_user_by_email("test_prosumer_user@seita.nl")
    num_users_before = User.query.count()

    # Find assets belonging to the user's organisation
    asset_query = GenericAsset.query.filter(
        GenericAsset.account_id == prosumer.account_id
    )
    assets_before = asset_query.all()
    assert (
        len(assets_before) > 0
    ), "Test assets should have been set up, otherwise we'd not be testing whether they're kept."

    # Find all the organisation's sensors
    sensors_before = []
    for asset in assets_before:
        sensors_before.extend(asset.sensors)

    # Count all the organisation's beliefs
    beliefs_query = TimedBelief.query.filter(
        TimedBelief.sensor_id.in_([sensor.id for sensor in sensors_before])
    )
    num_beliefs_before = beliefs_query.count()
    assert (
        num_beliefs_before > 0
    ), "Some beliefs should have been set up, otherwise we'd not be testing whether they're kept."

    # Delete the user
    delete_user(prosumer)
    assert find_user_by_email("test_prosumer_user@seita.nl") is None
    assert User.query.count() == num_users_before - 1

    # Check whether the organisation's assets, sensors and beliefs were kept
    assets_after = asset_query.all()
    assert assets_after == assets_before

    num_beliefs_after = beliefs_query.count()
    assert num_beliefs_after == num_beliefs_before
