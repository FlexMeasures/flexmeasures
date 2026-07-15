"""Unit tests for the DeviceInventory: classification of flex-model entries and
canonical device enumeration. These tests run without a database; sensors are
unpersisted model instances with manually assigned ids.
"""

from datetime import timedelta

import pytest
from marshmallow import ValidationError

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.planning.devices import (
    DeviceInventory,
    DeviceRole,
)


def make_sensor(sensor_id: int, unit: str = "kW") -> Sensor:
    sensor = Sensor(
        name=f"sensor {sensor_id}",
        generic_asset_id=1,
        unit=unit,
        event_resolution=timedelta(hours=1) if unit == "kW" else timedelta(0),
    )
    sensor.id = sensor_id
    return sensor


@pytest.mark.parametrize("stock_only_position", [0, 1, 2])
def test_stock_only_entry_position_does_not_shift_devices(stock_only_position):
    """Devices keep their properties and order regardless of where a stock-only entry sits."""
    soc = make_sensor(100, unit="kWh")
    power_a = make_sensor(1)
    power_b = make_sensor(2)

    stock_only_entry = {
        "state_of_charge": soc,
        "soc_at_start": 0.0,
        "soc_max": 0.1,
    }
    device_entries = [
        {"sensor": power_a, "state_of_charge": soc, "power_capacity_in_mw": 0.001},
        {"sensor": power_b, "power_capacity_in_mw": 0.009},
    ]
    flex_model = device_entries.copy()
    flex_model.insert(stock_only_position, stock_only_entry)

    inventory = DeviceInventory.from_flex_config(flex_model)

    assert [entry.role for entry in inventory.entries] == [
        DeviceRole.STOCK_ONLY if fm is stock_only_entry else DeviceRole.DEVICE
        for fm in flex_model
    ]
    # Device indices and properties are independent of the stock-only entry's position.
    assert inventory.num_flexible == 2
    assert inventory.power_sensors == [power_a, power_b]
    assert inventory.device_flex_models == device_entries
    assert [device.index for device in inventory.devices] == [0, 1]
    # Device A shares the stock described by the stock-only entry.
    assert inventory.stock_groups[soc.id] == [0]
    assert inventory.stock_params(soc.id) is stock_only_entry


def test_stock_keys_shared_between_params_and_groups():
    """Every stock group must be able to look up its SoC parameters, also for devices
    without a state-of-charge sensor and in the presence of stock-only entries."""
    soc = make_sensor(100, unit="kWh")
    power_a = make_sensor(1)
    power_c = make_sensor(3)

    device_c_entry = {
        "sensor": power_c,
        "soc_at_start": 0.0,
        "soc_max": 0.1,
    }
    inventory = DeviceInventory.from_flex_config(
        [
            {"state_of_charge": soc, "soc_at_start": 0.0},
            {"sensor": power_a, "state_of_charge": soc},
            device_c_entry,  # no state-of-charge sensor, own SoC parameters
        ]
    )

    for stock_key, devices in inventory.stock_groups.items():
        assert inventory.stock_params(stock_key) is not None, (
            f"Stock group {stock_key} (devices {devices}) cannot find its SoC "
            "parameters; its key is missing from stock_entries."
        )
    device_c = inventory.devices[1]
    assert device_c.power_sensor is power_c
    assert inventory.stock_params(device_c.stock_key) is device_c_entry


def test_single_sensor_mode():
    """A dict flex-model describes one device, whose power sensor is the scheduler's target."""
    power = make_sensor(1)
    flex_model = {"soc_at_start": 0.0, "soc_max": 0.1}

    inventory = DeviceInventory.from_flex_config(flex_model, sensor=power)

    assert inventory.is_single_sensor_mode
    assert inventory.num_flexible == 1
    device = inventory.devices[0]
    assert device.role == DeviceRole.DEVICE
    assert device.power_sensor is power
    assert device.index == 0
    # The single device has no state-of-charge sensor, so it keeps its own SoC
    # parameters under its synthetic stock key.
    assert inventory.stock_groups == {device.stock_key: [0]}
    assert inventory.stock_params(device.stock_key) is flex_model


def test_single_sensor_mode_with_state_of_charge_sensor():
    power = make_sensor(1)
    soc = make_sensor(100, unit="kWh")
    flex_model = {"state_of_charge": soc, "soc_at_start": 0.0}

    inventory = DeviceInventory.from_flex_config(flex_model, sensor=power)

    device = inventory.devices[0]
    assert device.role == DeviceRole.DEVICE
    assert device.stock_key == soc.id
    assert inventory.stock_params(soc.id) is flex_model


def test_nested_output_reference_resolves_power_sensor():
    """An entry referencing its power sensor only via a nested consumption/production
    output reference is a schedulable device, not a stock-only entry."""
    soc = make_sensor(100, unit="kWh")
    output = make_sensor(5)

    inventory = DeviceInventory.from_flex_config(
        [
            {
                "state_of_charge": soc,
                "consumption": {"sensor": output},
                "soc_at_start": 0.0,
            },
        ]
    )

    assert inventory.num_flexible == 1
    device = inventory.devices[0]
    assert device.role == DeviceRole.DEVICE
    assert device.power_sensor is output
    assert device.consumption_sensor is output
    assert device.stock_key == soc.id


def test_asset_only_entry_is_a_device_without_power_sensor():
    """An entry with neither a sensor nor a state-of-charge reference is still a device."""
    fake_asset = object()

    inventory = DeviceInventory.from_flex_config(
        [{"asset": fake_asset, "power_capacity_in_mw": 0.001}]
    )

    assert inventory.num_flexible == 1
    device = inventory.devices[0]
    assert device.role == DeviceRole.DEVICE
    assert device.power_sensor is None
    assert device.asset is fake_asset


def test_commodity_enumeration_includes_inflexible_tail():
    """Inflexible devices follow the flexible devices: top-level (electricity) sensors
    first, then each commodity context's own sensors, in context order."""
    inventory = DeviceInventory.from_flex_config(
        [
            {"sensor": make_sensor(1), "commodity": "electricity"},
            {"sensor": make_sensor(2), "commodity": "gas"},
            {"sensor": make_sensor(3)},  # defaults to electricity
        ],
        flex_context={
            "inflexible_device_sensors": [make_sensor(11), make_sensor(12)],
            "commodity_contexts": [
                {"commodity": "gas", "inflexible_device_sensors": [make_sensor(13)]},
            ],
        },
    )

    assert inventory.commodity_to_devices["electricity"] == [0, 2, 3, 4]
    assert inventory.commodity_to_devices["gas"] == [1, 5]
    assert inventory.num_scheduled == 6
    assert [device.sensor_id for device in inventory.inflexible_devices] == [11, 12, 13]
    assert inventory.by_index(5).commodity == "gas"


def test_electricity_group_exists_even_without_electricity_devices():
    """The electricity commodity group is always present (inflexible devices are
    electricity by default), even when empty."""
    inventory = DeviceInventory.from_flex_config(
        [{"sensor": make_sensor(1), "commodity": "gas"}]
    )
    assert inventory.commodity_to_devices == {"gas": [0], "electricity": []}


def test_by_sensor_id():
    power_a = make_sensor(1)
    power_b = make_sensor(2)
    inventory = DeviceInventory.from_flex_config(
        [
            {"sensor": power_a},
            {"sensor": power_b},
            {"sensor": power_b},  # two devices may share a power sensor
        ]
    )
    assert [device.index for device in inventory.by_sensor_id(1)] == [0]
    assert [device.index for device in inventory.by_sensor_id(2)] == [1, 2]
    assert inventory.by_sensor_id(3) == []


def test_state_of_charge_as_time_series_forms_own_stock():
    """A state of charge given as a value or time series (rather than a sensor
    reference) cannot link devices into a shared stock: the device keeps its own
    (synthetic) stock, with its own SoC parameters."""
    power = make_sensor(1)
    flex_model = {
        "state_of_charge": [{"start": "2015-01-01T00:00+01", "value": "3.1 MWh"}],
        "soc_at_start": 3.1,
    }

    inventory = DeviceInventory.from_flex_config(flex_model, sensor=power)

    device = inventory.devices[0]
    assert device.role == DeviceRole.DEVICE
    assert device.stock_key < 0  # synthetic
    assert inventory.stock_params(device.stock_key) is flex_model


def test_conflicting_stock_params_raise():
    """When multiple entries carry SoC parameters for the same stock, we fail fast
    rather than letting one entry silently win."""
    soc = make_sensor(100, unit="kWh")
    stock_only_entry = {"state_of_charge": soc, "soc_at_start": 0.0}
    device_with_params = {
        "sensor": make_sensor(1),
        "state_of_charge": soc,
        "soc_at_start": 1.0,
    }

    with pytest.raises(ValidationError, match="single entry"):
        DeviceInventory.from_flex_config([stock_only_entry, device_with_params])

    # A device entry without SoC parameters does not conflict.
    device_without_params = {"sensor": make_sensor(2), "state_of_charge": soc}
    inventory = DeviceInventory.from_flex_config(
        [stock_only_entry, device_without_params]
    )
    assert inventory.stock_params(soc.id) is stock_only_entry
