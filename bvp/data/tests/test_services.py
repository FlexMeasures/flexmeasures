from bvp.data.models.user import User
from bvp.data.services.users import (
    find_user_by_email,
    delete_user,
    toggle_activation_status_of,
)
from bvp.data.models.assets import Asset, Power


def test_delete_user(app):
    """Assert user has assets and power measurements. Deleting removes all of that."""
    users = User.query.filter(User.email == "test_prosumer@seita.nl").all()
    assert len(users) == 1
    prosumer: User = find_user_by_email("test_prosumer@seita.nl")
    assets = Asset.query.filter(Asset.owner_id == prosumer.id).all()
    assert len(assets) == 3
    asset_ids = [asset.id for asset in assets]
    for asset_id in asset_ids:
        num_power_measurements = Power.query.filter(Power.asset_id == asset_id).count()
        assert num_power_measurements == 96
    delete_user(prosumer)
    assert find_user_by_email("test_prosumer@seita.nl") is None
    assets = Asset.query.filter(Asset.owner_id == prosumer.id).all()
    assert len(assets) == 0
    for asset_id in asset_ids:
        num_power_measurements = Power.query.filter(Power.asset_id == asset_id).count()
        assert num_power_measurements == 0


def test_toggle_user_active_status(app):
    prosumer: User = find_user_by_email("test_prosumer@seita.nl")
    assert prosumer.active
    toggle_activation_status_of(prosumer)
    assert not prosumer.active
    toggle_activation_status_of(prosumer)
    assert prosumer.active
