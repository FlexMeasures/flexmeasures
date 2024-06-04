from datetime import timedelta

from flexmeasures import Asset, AssetType, Account, Sensor
from flexmeasures.data.models.generic_assets import (
    GenericAsset,
    GenericAssetInflexibleSensorRelationship,
)
from flexmeasures.ui.utils.breadcrumb_utils import get_ancestry

from timely_beliefs.sensors.func_store.knowledge_horizons import x_days_ago_at_y_oclock


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
        {"url": f"/assets/{assets[0].id}", "name": "Parent", "type": "Asset"},
    ]

    # check that the number of elements of the ancestry of each assets corresponds to 2 + levels
    for i, asset in enumerate(assets):
        assert len(get_ancestry(asset)) == i + 2

    # ancestry of the sensor
    sensor_ancestry = get_ancestry(sensor)
    assert sensor_ancestry[-1]["type"] == "Sensor"
    assert sensor_ancestry[0]["type"] == "Account"
    assert all(b["type"] == "Asset" for b in sensor_ancestry[1:-1])


class NewAsset:
    def __init__(self, db, setup_generic_asset_types, setup_accounts, new_asset_data):
        self.db = db
        self.setup_generic_asset_types = setup_generic_asset_types
        self.setup_accounts = setup_accounts
        self.new_asset_data = new_asset_data
        self.test_battery = None
        self.price_sensor = None

    def __enter__(self):
        if not self.new_asset_data:
            return self

        owner = (
            self.setup_accounts["Prosumer"]
            if self.new_asset_data.get("set_account")
            else None
        )
        self.test_battery = GenericAsset(
            name=self.new_asset_data["asset_name"],
            generic_asset_type=self.setup_generic_asset_types["battery"],
            owner=owner,
            attributes={"some-attribute": "some-value", "sensors_to_show": [1, 2]},
        )
        self.db.session.add(self.test_battery)
        self.db.session.flush()

        unit = self.new_asset_data.get("sensor_unit", "EUR/MWh")
        self.price_sensor = Sensor(
            name=self.new_asset_data["sensor_name"],
            generic_asset=self.test_battery,
            event_resolution=timedelta(hours=1),
            unit=unit,
            knowledge_horizon=(
                x_days_ago_at_y_oclock,
                {"x": 1, "y": 12, "z": "Europe/Paris"},
            ),
            attributes=dict(
                daily_seasonality=True,
                weekly_seasonality=True,
                yearly_seasonality=True,
            ),
        )
        self.db.session.add(self.price_sensor)
        self.db.session.flush()

        if self.new_asset_data.get("set_production_price_sensor_id"):
            self.test_battery.production_price_sensor_id = self.price_sensor.id
            self.db.session.add(self.test_battery)
        if self.new_asset_data.get("have_linked_sensors"):
            relationship = GenericAssetInflexibleSensorRelationship(
                generic_asset_id=self.test_battery.id,
                inflexible_sensor_id=self.price_sensor.id,
            )
            self.db.session.add(relationship)

        self.db.session.commit()

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.new_asset_data:
            return

        # Delete price_sensor and test_battery
        self.db.session.delete(self.price_sensor)
        self.db.session.delete(self.test_battery)
        self.db.session.commit()
