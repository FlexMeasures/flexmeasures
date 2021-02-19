import pytest

from flask_security.utils import hash_password

from flexmeasures.data.models.user import User, Role
from flexmeasures.data.services.users import (
    create_user,
    find_user_by_email,
    delete_user,
    InvalidFlexMeasuresUser,
)
from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.models.data_sources import DataSource


def test_create_user(app):
    """Create a user"""
    num_users = User.query.count()
    user = create_user(
        email="new_prosumer@seita.nl",
        password=hash_password("testtest"),
        user_roles=["Prosumer"],
    )
    assert User.query.count() == num_users + 1
    assert user.email == "new_prosumer@seita.nl"
    assert user.username == "new_prosumer"
    assert user.roles == [Role.query.filter_by(name="Prosumer").one_or_none()]
    assert DataSource.query.filter_by(user_id=user.id).one_or_none()
    assert DataSource.query.filter_by(name=user.username).one_or_none()


def test_create_invalid_user(app):
    """A few invalid attempts to create a user"""
    with pytest.raises(InvalidFlexMeasuresUser) as exc_info:
        create_user(password=hash_password("testtest"), user_roles=["Prosumer"])
    assert "No email" in str(exc_info.value)
    with pytest.raises(InvalidFlexMeasuresUser) as exc_info:
        create_user(
            email="test_prosumer_AT_seita.nl",
            password=hash_password("testtest"),
            user_roles=["Prosumer"],
        )
        assert "not a valid" in str(exc_info.value)
    """ # This check is disabled during testing, as testing should work without internet and be fast
    with pytest.raises(InvalidFlexMeasuresUser) as exc_info:
        create_user(
            email="test_prosumer@sdkkhflzsxlgjxhglkzxjhfglkxhzlzxcvlzxvb.nl",
            password=hash_password("testtest"),
            user_roles=["Prosumer"],
        )
    assert "not seem to be deliverable" in str(exc_info.value)
    """
    with pytest.raises(InvalidFlexMeasuresUser) as exc_info:
        create_user(
            email="test_prosumer@seita.nl",
            password=hash_password("testtest"),
            user_roles=["Prosumer"],
        )
    assert "already exists" in str(exc_info.value)
    with pytest.raises(InvalidFlexMeasuresUser) as exc_info:
        create_user(
            email="new_prosumer@seita.nl",
            username="Test Prosumer",
            password=hash_password("testtest"),
            user_roles=["Prosumer"],
        )
    assert "already exists" in str(exc_info.value)


def test_delete_user(app):
    """Assert user has assets and power measurements. Deleting removes all of that."""
    prosumer: User = find_user_by_email("test_prosumer@seita.nl")
    num_users_before = User.query.count()
    user_assets_with_measurements_before = Asset.query.filter(
        Asset.owner_id == prosumer.id, Asset.asset_type_name.in_(["wind", "solar"])
    ).all()
    asset_ids = [asset.id for asset in user_assets_with_measurements_before]
    for asset_id in asset_ids:
        num_power_measurements = Power.query.filter(Power.asset_id == asset_id).count()
        assert num_power_measurements == 96
    delete_user(prosumer)
    assert find_user_by_email("test_prosumer@seita.nl") is None
    user_assets_after = Asset.query.filter(Asset.owner_id == prosumer.id).all()
    assert len(user_assets_after) == 0
    assert User.query.count() == num_users_before - 1
    for asset_id in asset_ids:
        num_power_measurements = Power.query.filter(Power.asset_id == asset_id).count()
        assert num_power_measurements == 0
