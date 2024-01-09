from flexmeasures import Asset, AssetType, Account, Sensor
from flexmeasures.ui.utils.breadcrumb_utils import get_ancestry


def test_get_ancestry(app, db):
    account = Account(name="Test Account")
    asset_type = AssetType(name="TestAssetType")

    parent_asset = Asset(name="Parent", generic_asset_type=asset_type, owner=account)
    assets = [parent_asset]
    for i in range(4):
        child_asset = Asset(
            name=f"Child {i}",
            generic_asset_type=asset_type,
            owner=account,
            parent_asset=parent_asset,
        )
        assets.append(child_asset)
        parent_asset = child_asset

    sensor = Sensor(name="Test Sensor", generic_asset=child_asset)

    db.session.add_all([account, asset_type, sensor] + assets)
    db.session.commit()

    # ancestry of a public account
    assert get_ancestry(None) == [{"url": None, "name": "PUBLIC", "type": "Account"}]

    # ancestry of an account
    account_id = account.id
    assert get_ancestry(account) == [
        {"url": f"/accounts/{account_id}", "name": "Test Account", "type": "Account"}
    ]

    # ancestry of a parentless asset
    assert get_ancestry(assets[0]) == [
        {"url": f"/accounts/{account_id}", "name": "Test Account", "type": "Account"},
        {"url": f"/assets/{assets[0].id}/", "name": "Parent", "type": "Asset"},
    ]

    # check that the number of elements of the ancestry of each assets corresponds to 2 + levels
    for i, asset in enumerate(assets):
        assert len(get_ancestry(asset)) == i + 2

    # ancestry of the sensor
    sensor_ancestry = get_ancestry(sensor)
    assert sensor_ancestry[-1]["type"] == "Sensor"
    assert sensor_ancestry[0]["type"] == "Account"
    assert all(b["type"] == "Asset" for b in sensor_ancestry[1:-1])
