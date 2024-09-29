import pytest
from unittest.mock import patch

from flexmeasures.ui.crud.assets import AssetForm
from flexmeasures.ui.tests.test_utils import NewAsset


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
def test_with_price_sensors(
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

        with patch(
            "flexmeasures.ui.crud.assets.forms.get_allowed_price_sensor_data",
            return_value=allowed_price_sensor_data,
        ) as mock_method:
            form.with_price_sensors(new_asset_decorator.test_battery, 1)
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

        with patch(
            "flexmeasures.ui.crud.assets.forms.get_allowed_inflexible_sensor_data",
            return_value=allowed_inflexible_sensor_data,
        ) as mock_method:
            form.with_inflexible_sensors(new_asset_decorator.test_battery, 1)
            assert mock_method.called_once_with(1)
            assert form.inflexible_device_sensor_ids.choices == expect_choices
            assert form.inflexible_device_sensor_ids.default == expect_default
