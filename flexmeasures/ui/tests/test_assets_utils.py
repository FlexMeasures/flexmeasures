import pytest

from flexmeasures.ui.crud.assets import (
    get_allowed_price_sensor_data,
    get_allowed_inflexible_sensor_data,
)
from flexmeasures.ui.tests.test_utils import NewAsset


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
    with NewAsset(
        db, setup_generic_asset_types, setup_accounts, new_asset
    ) as new_asset_decorator:
        price_sensor_data = get_allowed_price_sensor_data(account_argument)
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
    with NewAsset(
        db, setup_generic_asset_types, setup_accounts, new_asset
    ) as new_asset_decorator:
        price_sensor_data = get_allowed_inflexible_sensor_data(account_argument)
        if expect_new_asset_sensor:
            assert len(price_sensor_data) == 1
            assert (
                price_sensor_data[new_asset_decorator.price_sensor.id]
                == f'{new_asset["asset_name"]}:{new_asset["sensor_name"]}'
            )
