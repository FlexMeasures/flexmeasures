import pytest

from flexmeasures.utils.unit_utils import (
    determine_flow_unit,
    determine_stock_unit,
    is_energy_unit,
    is_power_unit,
    u,
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


def test_h_denotes_hour_and_not_planck_constant():
    assert u.Quantity("h").dimensionality == u.Quantity("hour").dimensionality
    assert (
        u.Quantity("hbar").dimensionality
        == u.Quantity("planck_constant").dimensionality
    )


@pytest.mark.parametrize(
    "unit, power_unit",
    [
        ("EUR/MWh", False),
        ("KRW/kWh", False),
        ("kWh", False),
        ("kW", True),
        ("watt", True),
        ("°C", False),
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
    ],
)
def test_is_energy_unit(unit: str, energy_unit: bool):
    assert is_energy_unit(unit) is energy_unit
