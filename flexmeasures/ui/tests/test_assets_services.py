import pytest
from unittest.mock import patch

from datetime import timedelta
from timely_beliefs.sensors.func_store.knowledge_horizons import x_days_ago_at_y_oclock

from flexmeasures.data.models.generic_assets import (
    GenericAsset,
    GenericAssetInflexibleSensorRelationship,
)
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.ui.crud.assets.services import AssetForm


@pytest.mark.parametrize(
    "new_asset, account_argument, expect_new_asset_sensor",
    [
        # No asset, no account - get the default sensors
        (None, None, False),
        # No account on asset and function call - get new asset sensors
        (
            {
                "asset_name": "No account asset",
                "sensor_name": "No account asset sensor",
            },
            None,
            True,
        ),
        # Asset with account, function call without - do not get new asset sensors
        (
            {
                "asset_name": "Have account asset",
                "sensor_name": "Have account asset sensor",
                "set_account": True,
            },
            None,
            False,
        ),
        # Asset without account, function call with - do not get new asset sensors
        (
            {
                "asset_name": "Have account asset",
                "sensor_name": "Have account asset sensor",
            },
            1,
            False,
        ),
        # Asset has the same account that function call - get new asset sensors
        (
            {
                "asset_name": "Have account asset",
                "sensor_name": "Have account asset sensor",
                "set_account": True,
            },
            1,
            True,
        ),
        # Asset and function call have different accounts - do not get new asset sensors
        (
            {
                "asset_name": "Have account asset",
                "sensor_name": "Have account asset sensor",
                "set_account": True,
            },
            1000,
            False,
        ),
        # New asset sensor has different unit - do not get new asset sensors
        (
            {
                "asset_name": "No account asset",
                "sensor_name": "No account asset sensor",
                "sensor_unit": "kWh",
            },
            None,
            False,
        ),
    ],
)
def test_get_allowed_price_sensor_data(
    db,
    setup_generic_asset_types,
    setup_accounts,
    new_asset,
    account_argument,
    expect_new_asset_sensor,
):
    form = AssetForm()
    with NewAsset(
        db, setup_generic_asset_types, setup_accounts, new_asset
    ) as new_asset_decorator:
        price_sensor_data = form.get_allowed_price_sensor_data(account_argument)
        if expect_new_asset_sensor:
            assert len(price_sensor_data) == 3
            assert (
                price_sensor_data[new_asset_decorator.price_sensor.id]
                == f'{new_asset["asset_name"]}:{new_asset["sensor_name"]}'
            )

    # we are adding these sensors in assets without account by default
    assert price_sensor_data[1] == "epex:epex_da"
    assert price_sensor_data[2] == "epex:epex_da_production"


@pytest.mark.parametrize(
    "new_asset, account_argument, expect_new_asset_sensor",
    [
        # No asset, no account - get the default sensors
        (None, None, False),
        # No account on asset and function call - get new asset sensors
        (
            {
                "asset_name": "No account asset",
                "sensor_name": "No account asset sensor",
                "sensor_unit": "kWh",
            },
            None,
            True,
        ),
        # Asset with account, function call without - do not get new asset sensors
        (
            {
                "asset_name": "Have account asset",
                "sensor_name": "Have account asset sensor",
                "sensor_unit": "kWh",
                "set_account": True,
            },
            None,
            False,
        ),
        # Asset without account, function call with - do not get new asset sensors
        (
            {
                "asset_name": "Have account asset",
                "sensor_name": "Have account asset sensor",
                "sensor_unit": "kWh",
            },
            1,
            False,
        ),
        # Asset has the same account that function call - get new asset sensors
        (
            {
                "asset_name": "Have account asset",
                "sensor_name": "Have account asset sensor",
                "sensor_unit": "kWh",
                "set_account": True,
            },
            1,
            True,
        ),
        # Asset and function call have different accounts - do not get new asset sensors
        (
            {
                "asset_name": "Have account asset",
                "sensor_name": "Have account asset sensor",
                "sensor_unit": "kWh",
                "set_account": True,
            },
            1000,
            False,
        ),
        # New asset sensor has energy unit - still use it
        (
            {
                "asset_name": "No account asset",
                "sensor_name": "No account asset sensor",
                "sensor_unit": "kW",
            },
            None,
            True,
        ),
        # New asset sensor has temperature unit - do not get new asset sensors
        (
            {
                "asset_name": "No account asset",
                "sensor_name": "No account asset sensor",
                "sensor_unit": "°C",
            },
            None,
            False,
        ),
    ],
)
def test_get_allowed_inflexible_sensor_data(
    db,
    setup_generic_asset_types,
    setup_accounts,
    new_asset,
    account_argument,
    expect_new_asset_sensor,
):
    form = AssetForm()
    with NewAsset(
        db, setup_generic_asset_types, setup_accounts, new_asset
    ) as new_asset_decorator:
        price_sensor_data = form.get_allowed_inflexible_sensor_data(account_argument)
        if expect_new_asset_sensor:
            assert len(price_sensor_data) == 1
            assert (
                price_sensor_data[new_asset_decorator.price_sensor.id]
                == f'{new_asset["asset_name"]}:{new_asset["sensor_name"]}'
            )


@pytest.mark.parametrize(
    "new_asset, allowed_price_sensor_data, expect_choices, expect_default",
    [
        # No asset, no allowed_price_sensor_data
        (None, dict(), [(-1, "--Select sensor id--")], (-1, "--Select sensor id--")),
        # Have production_price_sensor_id, no allowed_price_sensor_data
        (
            {
                "set_production_price_sensor_id": True,
                "asset_name": "Asset name",
                "sensor_name": "Sensor name",
            },
            dict(),
            [(-1, "--Select sensor id--"), ("SENSOR_ID", "Asset name:Sensor name")],
            ("SENSOR_ID", "Asset name:Sensor name"),
        ),
        # Have production_price_sensor_id and allowed_price_sensor_data
        (
            {
                "set_production_price_sensor_id": True,
                "asset_name": "Asset name",
                "sensor_name": "Sensor name",
            },
            {1000: "Some asset name:Some sensor name"},
            [
                (-1, "--Select sensor id--"),
                (1000, "Some asset name:Some sensor name"),
                ("SENSOR_ID", "Asset name:Sensor name"),
            ],
            ("SENSOR_ID", "Asset name:Sensor name"),
        ),
        # No production_price_sensor_id, have allowed_price_sensor_data
        (
            {"asset_name": "Asset name", "sensor_name": "Sensor name"},
            {1000: "Some asset name:Some sensor name"},
            [(-1, "--Select sensor id--"), (1000, "Some asset name:Some sensor name")],
            (-1, "--Select sensor id--"),
        ),
    ],
)
def test_with_price_senors(
    db,
    setup_generic_asset_types,
    setup_accounts,
    new_asset,
    allowed_price_sensor_data,
    expect_choices,
    expect_default,
):
    form = AssetForm()
    with NewAsset(
        db, setup_generic_asset_types, setup_accounts, new_asset
    ) as new_asset_decorator:
        sensor_id = (
            new_asset_decorator.price_sensor.id
            if new_asset_decorator and new_asset_decorator.price_sensor
            else None
        )
        expect_default = tuple(
            sensor_id if element == "SENSOR_ID" else element
            for element in expect_default
        )
        expect_choices = [
            tuple(
                sensor_id if element == "SENSOR_ID" else element for element in choice
            )
            for choice in expect_choices
        ]

        with patch.object(
            AssetForm,
            "get_allowed_price_sensor_data",
            return_value=allowed_price_sensor_data,
        ) as mock_method:
            form.with_price_senors(new_asset_decorator.test_battery, 1)
            assert mock_method.called_once_with(1)
            # check production_price_sensor only as consumption_price is processed the same way
            assert form.production_price_sensor_id.choices == expect_choices
            assert form.production_price_sensor_id.default == expect_default


@pytest.mark.parametrize(
    "new_asset, allowed_inflexible_sensor_data, expect_choices, expect_default",
    [
        # No asset, no allowed_inflexible_sensor_data
        (None, dict(), [(-1, "--Select sensor id--")], [-1]),
        # Asset without linked sensors, no allowed_inflexible_sensor_data
        (
            {"asset_name": "Asset name", "sensor_name": "Sensor name"},
            dict(),
            [(-1, "--Select sensor id--")],
            [-1],
        ),
        # Asset without linked sensors, have allowed_inflexible_sensor_data
        (
            {"asset_name": "Asset name", "sensor_name": "Sensor name"},
            {1000: "Some asset name:Some sensor name"},
            [(-1, "--Select sensor id--"), (1000, "Some asset name:Some sensor name")],
            [-1],
        ),
        # Have linked sensors, have allowed_inflexible_sensor_data
        (
            {
                "asset_name": "Asset name",
                "sensor_name": "Sensor name",
                "have_linked_sensors": True,
            },
            {1000: "Some asset name:Some sensor name"},
            [
                (-1, "--Select sensor id--"),
                (1000, "Some asset name:Some sensor name"),
                ("SENSOR_ID", "Asset name:Sensor name"),
            ],
            ["SENSOR_ID"],
        ),
    ],
)
def test_with_inflexible_sensors(
    db,
    setup_generic_asset_types,
    setup_accounts,
    new_asset,
    allowed_inflexible_sensor_data,
    expect_choices,
    expect_default,
):
    form = AssetForm()
    with NewAsset(
        db, setup_generic_asset_types, setup_accounts, new_asset
    ) as new_asset_decorator:
        sensor_id = (
            new_asset_decorator.price_sensor.id
            if new_asset_decorator and new_asset_decorator.price_sensor
            else None
        )
        expect_default = list(
            sensor_id if element == "SENSOR_ID" else element
            for element in expect_default
        )
        expect_choices = [
            tuple(
                sensor_id if element == "SENSOR_ID" else element for element in choice
            )
            for choice in expect_choices
        ]

        with patch.object(
            AssetForm,
            "get_allowed_inflexible_sensor_data",
            return_value=allowed_inflexible_sensor_data,
        ) as mock_method:
            form.with_inflexible_sensors(new_asset_decorator.test_battery, 1)
            assert mock_method.called_once_with(1)
            assert form.inflexible_device_sensor_ids.choices == expect_choices
            assert form.inflexible_device_sensor_ids.default == expect_default


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
