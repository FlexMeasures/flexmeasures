from datetime import timedelta

import pint.errors
import pytest

import pandas as pd

from flexmeasures.utils.unit_utils import (
    convert_units,
    determine_flow_unit,
    determine_stock_unit,
    determine_unit_conversion_multiplier,
    units_are_convertible,
    is_energy_unit,
    is_power_unit,
    ur,
)


@pytest.mark.parametrize(
    "from_unit, to_unit, expected_multiplier, expected_values",
    [
        ("%", "‰", 10, None),
        ("m/s", "km/h", 3.6, None),
        ("m³/h", "l/h", 1000, None),
        ("m³", "m³/h", 4, None),
        ("MW", "kW", 1000, None),
        ("%", "kWh", 0.5, None),  # i.e. 1% of 50 kWh (the capacity used in the test)
        ("kWh", "%", 2, None),  # i.e. 1 kWh = 2% of 50 kWh
        ("kWh", "kW", 4, None),
        ("kW", "kWh", 1 / 4, None),
        ("-W", "W", -1, None),
        ("l/(100km)", "l/km", 0.01, None),
        ("°C", "K", None, [273.15, 283.15, 284.15]),
        # no support for combining an offset unit with a scaling factor, but this is also overly specific
        # ("-°C", "K", None, [273.15, 263.15, 262.15]),
        # ("l/(10°C)", "l/(°C)", 0.1, None),
    ],
)
def test_convert_unit(
    from_unit,
    to_unit,
    expected_multiplier,
    expected_values,
):
    """Check some common unit conversions.

    Note that for the above expectations:
    - conversion from kWh to kW, and from m³ to m³/h, both depend on the event resolution set below
    - conversion from °C to K depends on the data values set below
    """
    data = pd.Series([0, 10.0, 11.0])
    converted_data: pd.Series = convert_units(
        data=data,
        from_unit=from_unit,
        to_unit=to_unit,
        event_resolution=timedelta(minutes=15),
        capacity="50 kWh",
    )
    if expected_multiplier is not None:
        expected_data = data * expected_multiplier
    else:
        expected_data = pd.Series(expected_values)
    pd.testing.assert_series_equal(converted_data, expected_data)


@pytest.mark.parametrize(
    "unit, time_unit, expected_unit",
    [
        ("m³", None, "m³/h"),
        ("kWh", None, "kW"),
        ("km", "h", "km/h"),
        ("m", "s", "m/s"),
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
        ("km³/h", None, "km³"),
        # ("hm³/h", None, "hm³"),  # todo: uncomment after switching to decimal unit registry
        ("kW", None, "kWh"),
        ("m/s", "s", "m"),
        ("m/s", "h", "km"),
        ("t/h", None, "t"),
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
    with pytest.raises(pint.errors.OffsetUnitCalculusError):
        # Not a conversion that can be specified as a multiplication
        determine_unit_conversion_multiplier("°C", "K")


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
        ("#", False),
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
