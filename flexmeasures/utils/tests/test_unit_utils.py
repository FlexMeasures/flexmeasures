from datetime import timedelta

import pint.errors
import pytest

import pandas as pd
import timely_beliefs as tb

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
    "from_unit, to_unit, timezone, input_values, expected_values",
    [
        # datetimes are converted to seconds since UNIX epoch
        (
            "datetime",
            "s",
            None,
            ["1970-01-01", "1970-01-02", "1970-01-03"],
            [0, 60 * 60 * 24, 60 * 60 * 48],
        ),
        # nothing overflows for the next 100 years
        (
            "datetime",
            "s",
            None,
            ["2123-05-02", "2123-05-03", "2123-05-04"],
            [4838659200, 4838659200 + 60 * 60 * 24, 4838659200 + 60 * 60 * 48],
        ),
        # Same as above, but day precedes month in input
        (
            "dayfirst datetime",
            "s",
            None,
            ["02-05-2123", "03-05-2123", "04-05-2123"],
            [4838659200, 4838659200 + 60 * 60 * 24, 4838659200 + 60 * 60 * 48],
        ),
        # Localize timezone-naive datetimes to UTC in case there is no sensor information available
        (
            "datetime",
            "s",
            None,
            ["2023-05-02 00:00:01", "2023-05-02 00:00:02", "2023-05-02 00:00:03"],
            [1682985601, 1682985602, 1682985603],
        ),
        # Localize timezone-naive datetimes to sensor's timezone in case that is available
        (
            "datetime",
            "s",
            "Europe/Amsterdam",
            ["2023-05-02 00:00:01", "2023-05-02 00:00:02", "2023-05-02 00:00:03"],
            [
                1682985601 - 60 * 60 * 2,
                1682985602 - 60 * 60 * 2,
                1682985603 - 60 * 60 * 2,
            ],
        ),
        # Timezone-aware datetimes work don't require localization
        (
            "datetime",
            "s",
            None,
            [
                "2023-05-02 00:00:01 +02:00",
                "2023-05-02 00:00:02 +02:00",
                "2023-05-02 00:00:03 +02:00",
            ],
            [
                1682985601 - 60 * 60 * 2,
                1682985602 - 60 * 60 * 2,
                1682985603 - 60 * 60 * 2,
            ],
        ),
        # Timezone-aware datetimes also means that the sensor timezone is irrelevant
        (
            "datetime",
            "s",
            "Asia/Seoul",
            [
                "2023-05-02 00:00:01 +02:00",
                "2023-05-02 00:00:02 +02:00",
                "2023-05-02 00:00:03 +02:00",
            ],
            [
                1682985601 - 60 * 60 * 2,
                1682985602 - 60 * 60 * 2,
                1682985603 - 60 * 60 * 2,
            ],
        ),
        # Timedeltas can be converted to units of time
        ("timedelta", "s", None, ["1 minute", "1 minute 2 seconds"], [60.0, 62.0]),
        # Convertible timedeltas include absolute days of 24 hours
        ("timedelta", "d", None, ["1 day", "1 day 12 hours"], [1.0, 1.5]),
        # Convertible timedeltas exclude nominal durations like month or year, which cannot be represented as a datetime.timedelta object
        # ("timedelta", "d", None, ["1 month", "1 year"], [30., 365.]),  # fails
    ],
)
def test_convert_special_unit(
    from_unit,
    to_unit,
    timezone,
    input_values,
    expected_values,
):
    """Check some special unit conversions."""
    data = pd.Series(input_values)
    if timezone:
        data.sensor = tb.Sensor("test", timezone=timezone)
    converted_data: pd.Series = convert_units(
        data=data,
        from_unit=from_unit,
        to_unit=to_unit,
    )
    print(converted_data)
    expected_data = pd.Series(expected_values)
    print(expected_data)
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
