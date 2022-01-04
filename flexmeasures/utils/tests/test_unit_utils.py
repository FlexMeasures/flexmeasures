from datetime import timedelta
import pytest

from flexmeasures.utils.unit_utils import (
    determine_flow_unit,
    determine_stock_unit,
    determine_unit_conversion_multiplier,
    units_are_convertible,
    is_energy_unit,
    is_power_unit,
    ur,
)


@pytest.mark.parametrize(
    "unit, time_unit, expected_unit",
    [
        ("m³", None, "m³/h"),
        ("kWh", None, "kW"),
        ("km", "h", "km/h"),
        ("m", "s", "km/h"),
    ],
)
def test_determine_flow_unit(
    unit,
    time_unit,
    expected_unit,
):
    if time_unit is None:
        assert determine_flow_unit(unit) == expected_unit
    else:
        assert determine_flow_unit(unit, time_unit) == expected_unit


@pytest.mark.parametrize(
    "unit, time_unit, expected_unit",
    [
        ("m³/h", None, "m³"),
        ("kW", None, "kWh"),
        ("m/s", "s", "m"),
        ("m/s", "h", "km"),
    ],
)
def test_determine_stock_unit(
    unit,
    time_unit,
    expected_unit,
):
    if time_unit is None:
        assert determine_stock_unit(unit) == expected_unit
    else:
        assert determine_stock_unit(unit, time_unit) == expected_unit


def test_determine_unit_conversion_multiplier():
    assert determine_unit_conversion_multiplier("kW", "W") == 1000
    assert determine_unit_conversion_multiplier("J/s", "W") == 1
    assert determine_unit_conversion_multiplier("Wh", "W", timedelta(minutes=10)) == 6
    assert determine_unit_conversion_multiplier("kWh", "MJ") == 3.6
    assert determine_unit_conversion_multiplier("°C", "K") == 274.15


def test_h_denotes_hour_and_not_planck_constant():
    assert ur.Quantity("h").dimensionality == ur.Quantity("hour").dimensionality
    assert (
        ur.Quantity("hbar").dimensionality
        == ur.Quantity("planck_constant").dimensionality
    )


def test_units_are_convertible():
    assert units_are_convertible("kW", "W")  # units just have different prefixes
    assert units_are_convertible(
        "J/s", "W"
    )  # units can be converted using some multiplier
    assert units_are_convertible(
        "Wh", "W"
    )  # units that represent a stock delta can, knowing the duration, be converted to a flow
    assert units_are_convertible("toe", "W")  # tonne of oil equivalent
    assert units_are_convertible("°C", "K")  # offset unit to absolute unit
    assert not units_are_convertible("°C", "W")
    assert not units_are_convertible("EUR/MWh", "W")
    assert not units_are_convertible("not-a-unit", "W")


@pytest.mark.parametrize(
    "unit, power_unit",
    [
        ("EUR/MWh", False),
        ("KRW/kWh", False),
        ("kWh", False),
        ("kW", True),
        ("watt", True),
        ("°C", False),
        ("", False),
        ("not-a-unit", False),
    ],
)
def test_is_power_unit(unit: str, power_unit: bool):
    assert is_power_unit(unit) is power_unit


@pytest.mark.parametrize(
    "unit, energy_unit",
    [
        ("EUR/MWh", False),
        ("KRW/kWh", False),
        ("kWh", True),
        ("kW", False),
        ("watthour", True),
        ("°C", False),
        ("", False),
        ("not-a-unit", False),
    ],
)
def test_is_energy_unit(unit: str, energy_unit: bool):
    assert is_energy_unit(unit) is energy_unit
