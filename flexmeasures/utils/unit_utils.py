"""Utility module for unit conversion

FlexMeasures stores units as strings in short scientific notation (such as 'kWh' to denote kilowatt-hour).
We use the pint library to convert data between compatible units (such as 'm/s' to 'km/h').
Three-letter currency codes (such as 'KRW' to denote South Korean Won) are valid units.
Note that converting between currencies requires setting up a sensor that registers conversion rates over time.
The preferred compact form for combinations of units can be derived automatically (such as 'kW*EUR/MWh' to 'EUR/h').
Time series with fixed resolution can be converted from units of flow to units of stock (such as 'kW' to 'kWh'), and vice versa.
Percentages can be converted to units of some physical capacity if a capacity is known (such as '%' to 'kWh').
"""

from __future__ import annotations

from datetime import timedelta

from moneyed import list_all_currencies, Currency
import numpy as np
import pandas as pd
import pint
import timely_beliefs as tb


# Create custom template
custom_template = [f"{c} = [currency_{c}]" for c in list_all_currencies()]

# Set up UnitRegistry with abbreviated scientific format
ur = pint.UnitRegistry(
    # non_int_type=decimal.Decimal,  # todo: switch to decimal unit registry, after https://github.com/hgrecco/pint/issues/1505
    preprocessors=[
        lambda s: s.replace("%", " percent "),
        lambda s: s.replace("‰", " permille "),
    ],
)
ur.load_definitions(custom_template)
ur.default_format = "~P"  # short pretty
ur.define("percent = 1 / 100 = %")
ur.define("permille = 1 / 1000 = ‰")


PREFERRED_UNITS = [
    "m",
    "h",
    "kg",
    "m/h",
    "W",
    "N",
    "Wh",
    "m**2",
    "m**3",
    "V",
    "A",
    "dimensionless",
] + [
    str(c) for c in list_all_currencies()
]  # todo: move to config setting, with these as a default (NB prefixes do not matter here, this is about SI base units, so km/h is equivalent to m/h)
PREFERRED_UNITS_DICT = dict(
    [(ur.parse_expression(x).dimensionality, x) for x in PREFERRED_UNITS]
)


def to_preferred(x: pint.Quantity) -> pint.Quantity:
    """From https://github.com/hgrecco/pint/issues/676#issuecomment-689157693"""
    dim = x.dimensionality
    if dim in PREFERRED_UNITS_DICT:

        compact_unit = x.to(PREFERRED_UNITS_DICT[dim]).to_compact()

        # todo: switch to decimal unit registry and then swap out the if statements below
        # if len(f"{compact_unit.magnitude}" + "{:~P}".format(compact_unit.units)) < len(
        #     f"{x.magnitude}" + "{:~P}".format(x.units)
        # ):
        #     return compact_unit
        if len("{:~P}".format(compact_unit.units)) < len("{:~P}".format(x.units)):
            return compact_unit
    return x


def is_valid_unit(unit: str) -> bool:
    """Return True if the pint library can work with this unit identifier."""
    try:
        ur.Quantity(unit)
    except Exception:  # noqa B902
        # in practice, we encountered pint.errors.UndefinedUnitError, ValueError and AttributeError,
        # but since there may be more, here we simply catch them all
        return False
    return True


def find_smallest_common_unit(units: list[str]) -> tuple[str, dict[str, float]]:
    """Select the smallest unit by comparing their magnitude when converted to base units.

    If the units are dimensionally incompatible (e.g. "kg" and "m"), returns "a.u." and default scaling factors of 1.

    For example:
    >>> find_smallest_common_unit(["MW", "kW", "W"])
    ('W', {'MW': 1000000.0, 'kW': 1000.0, 'W': 1.0})
    >>> find_smallest_common_unit(["kEUR", "EUR"])
    ('EUR', {'kEUR': 1000.0, 'EUR': 1.0})
    >>> find_smallest_common_unit(["cEUR/kWh", "EUR/MWh"])  # NB: has a floating point error
    ('EUR/MWh', {'cEUR/kWh': 10.000000000000002, 'EUR/MWh': 1.0})
    >>> find_smallest_common_unit(["%", "dimensionless"])
    ('%', {'%': 1.0, 'dimensionless': 100.0})
    >>> find_smallest_common_unit(["%", ""])
    ('%', {'%': 1.0, '': 100.0})
    >>> find_smallest_common_unit(["h", "s"])
    ('s', {'h': 3600.0, 's': 1.0})
    >>> find_smallest_common_unit(["kW", "m"])
    ('a.u.', {'kW': 1.0, 'm': 1.0})
    >>> find_smallest_common_unit(["EUR", "AUD"])
    ('a.u.', {'EUR': 1.0, 'AUD': 1.0})
    """
    if not units:
        return "a.u.", {}

    try:
        # Convert all to quantities and check dimensionality
        quantities = [1.0 * ur.parse_units(u) for u in units]
        dim = quantities[0].dimensionality

        if any(q.dimensionality != dim for q in quantities):
            return "a.u.", {unit: 1.0 for unit in units}

        # Get magnitudes in terms of base units
        base_mags = [ur.Quantity(1.0, u).to_base_units().magnitude for u in units]
        smallest_idx = base_mags.index(min(base_mags))
        smallest_unit = units[smallest_idx]

        # Compute scaling factors to smallest unit
        factors = {
            u: determine_unit_conversion_multiplier(u, smallest_unit) for u in units
        }

        return smallest_unit, factors

    except (pint.DimensionalityError, Exception):
        return "a.u.", {unit: 1.0 for unit in units}


def determine_unit_conversion_multiplier(
    from_unit: str, to_unit: str, duration: timedelta | None = None
):
    """Determine the value multiplier for a given unit conversion.
    If needed, requires a duration to convert from units of stock change to units of flow, or vice versa.
    """
    if from_unit == "":
        from_unit = "dimensionless"
    if to_unit == "":
        to_unit = "dimensionless"
    scalar = ur.Quantity(from_unit) / ur.Quantity(to_unit)
    if scalar.dimensionality == ur.Quantity("h").dimensionality:
        # Convert a stock change to a flow
        if duration is None:
            raise ValueError(
                f"Cannot convert units from {from_unit} to {to_unit} without known duration."
            )
        return scalar.to_timedelta() / duration
    elif scalar.dimensionality == ur.Quantity("1/h").dimensionality:
        # Convert a flow to a stock change
        if duration is None:
            raise ValueError(
                f"Cannot convert units from {from_unit} to {to_unit} without known duration."
            )
        return duration / (1 / scalar).to_timedelta()
    elif scalar.dimensionality != ur.Quantity("dimensionless").dimensionality:
        raise ValueError(
            f"Unit conversion from {from_unit} to {to_unit} doesn't seem possible."
        )
    return scalar.to_reduced_units().magnitude


def determine_flow_unit(stock_unit: str, time_unit: str = "h"):
    """For example:
    >>> determine_flow_unit("m³")
    'm³/h'
    >>> determine_flow_unit("kWh")
    'kW'
    """
    flow = to_preferred(ur.Quantity(stock_unit) / ur.Quantity(time_unit))
    return "{:~P}".format(flow.units)


def determine_stock_unit(flow_unit: str, time_unit: str = "h"):
    """Determine the shortest unit of stock, given a unit of flow.

    For example:
    >>> determine_stock_unit("m³/h")
    'm³'
    >>> determine_stock_unit("kW")
    'kWh'
    """
    stock = to_preferred(ur.Quantity(flow_unit) * ur.Quantity(time_unit))
    return "{:~P}".format(stock.units)


def units_are_convertible(
    from_unit: str, to_unit: str, duration_known: bool = True
) -> bool:
    """For example, a sensor with W units allows data to be posted with units:
    >>> units_are_convertible("kW", "W")  # units just have different prefixes
    True
    >>> units_are_convertible("J/s", "W")  # units can be converted using some multiplier
    True
    >>> units_are_convertible("Wh", "W")  # units that represent a stock delta can, knowing the duration, be converted to a flow
    True
    >>> units_are_convertible("°C", "W")
    False
    """
    if not is_valid_unit(from_unit) or not is_valid_unit(to_unit):
        return False
    scalar = (
        ur.Quantity(from_unit).to_base_units() / ur.Quantity(to_unit).to_base_units()
    )
    if duration_known:
        return scalar.dimensionality in (
            ur.Quantity("h").dimensionality,
            ur.Quantity("dimensionless").dimensionality,
        )
    return scalar.dimensionality == ur.Quantity("dimensionless").dimensionality


def is_power_unit(unit: str) -> bool:
    """For example:
    >>> is_power_unit("kW")
    True
    >>> is_power_unit("°C")
    False
    >>> is_power_unit("kWh")
    False
    >>> is_power_unit("EUR/MWh")
    False
    """
    if not is_valid_unit(unit):
        return False
    return ur.Quantity(unit).dimensionality == ur.Quantity("W").dimensionality


def is_energy_unit(unit: str) -> bool:
    """For example:
    >>> is_energy_unit("kW")
    False
    >>> is_energy_unit("°C")
    False
    >>> is_energy_unit("kWh")
    True
    >>> is_energy_unit("EUR/MWh")
    False
    """
    if not is_valid_unit(unit):
        return False
    return ur.Quantity(unit).dimensionality == ur.Quantity("Wh").dimensionality


def is_currency_unit(unit: str | pint.Quantity | pint.Unit) -> bool:
    """For Example:
    >>> is_currency_unit("EUR")
    True
    >>> is_currency_unit("KRW")
    True
    >>> is_currency_unit("potatoe")
    False
    >>> is_currency_unit("MW")
    False
    """
    if isinstance(unit, pint.Quantity):
        return is_currency_unit(unit.units)
    if isinstance(unit, pint.Unit):
        return is_currency_unit(str(unit))

    return Currency(code=unit) in list_all_currencies()


def is_price_unit(unit: str) -> bool:
    """For example:
    >>> is_price_unit("EUR/MWh")
    True
    >>> is_price_unit("KRW/MWh")
    True
    >>> is_price_unit("KRW/MW")
    True
    >>> is_price_unit("beans/MW")
    False
    """
    if (
        unit[:3] in [str(c) for c in list_all_currencies()]
        and len(unit) > 3
        and unit[3] == "/"
    ):
        return True
    return False


def is_energy_price_unit(unit: str) -> bool:
    """For example:
    >>> is_energy_price_unit("EUR/MWh")
    True
    >>> is_energy_price_unit("KRW/MWh")
    True
    >>> is_energy_price_unit("KRW/MW")
    False
    >>> is_energy_price_unit("beans/MW")
    False
    """
    if is_price_unit(unit) and is_energy_unit(unit[4:]):
        return True
    return False


def is_capacity_price_unit(unit: str) -> bool:
    """For example:
    >>> is_capacity_price_unit("EUR/MW")
    True
    >>> is_capacity_price_unit("KRW/MW")
    True
    >>> is_capacity_price_unit("KRW/MWh")
    False
    >>> is_capacity_price_unit("beans/MWh")
    False
    """
    if is_price_unit(unit) and is_power_unit(unit[4:]):
        return True
    return False


def is_speed_unit(unit: str) -> bool:
    """For example:
    >>> is_speed_unit("m/s")
    True
    >>> is_speed_unit("km/h")
    True
    >>> is_speed_unit("W")
    False
    >>> is_speed_unit("m/s²")
    False
    """
    if not is_valid_unit(unit):
        return False
    return ur.Quantity(unit).dimensionality == ur.Quantity("m/s").dimensionality


def get_unit_dimension(unit: str) -> str:
    """For example:
    >>> get_unit_dimension("kW")
    'power'
    >>> get_unit_dimension("kWh")
    'energy'
    >>> get_unit_dimension("EUR/MWh")
    'energy price'
    >>> get_unit_dimension("EUR/kW")  # e.g. a capacity price or a peak price
    'price'
    >>> get_unit_dimension("AUD")
    'currency'
    >>> get_unit_dimension("%")
    'percentage'
    >>> get_unit_dimension("°C")
    'temperature'
    >>> get_unit_dimension("m")
    'length'
    >>> get_unit_dimension("h")
    'time'
    >>> get_unit_dimension("m/s")
    'speed'
    """
    if is_power_unit(unit):
        return "power"
    if is_energy_unit(unit):
        return "energy"
    if is_energy_price_unit(unit):
        return "energy price"
    if is_price_unit(unit):
        return "price"
    if is_currency_unit(unit):
        return "currency"
    if is_speed_unit(unit):
        return "speed"
    if unit == "%":
        return "percentage"
    dimensions = ur.Quantity(unit).dimensionality
    if len(dimensions) == 1:
        return list(dimensions.keys())[0][1:-1]
    return "value"


def _convert_time_units(
    data: tb.BeliefsSeries | pd.Series | list[int | float] | int | float,
    from_unit: str,
    to_unit: str,
):
    """Convert data with datetime or timedelta dtypes to float values.

    Use Unix epoch or the requested time unit, respectively.
    """
    if not to_unit[0].isdigit():
        # unit abbreviations passed to pd.Timedelta need a number (so, for example, h becomes 1h)
        to_unit = f"1{to_unit}"
    if "datetime" in from_unit:
        dt_data = pd.to_datetime(
            data, dayfirst=True if "dayfirst" in from_unit else False
        )
        # localize timezone naive data to the sensor's timezone, if available
        if dt_data.dt.tz is None:
            timezone = data.sensor.timezone if hasattr(data, "sensor") else "utc"
            dt_data = dt_data.dt.tz_localize(timezone)
        return (dt_data - pd.Timestamp("1970-01-01", tz="utc")) // pd.Timedelta(to_unit)
    else:
        return data / pd.Timedelta(to_unit)


def convert_units(
    data: tb.BeliefsSeries | pd.Series | list[int | float] | int | float,
    from_unit: str,
    to_unit: str,
    event_resolution: timedelta | None = None,
    capacity: str | None = None,
) -> pd.Series | list[int | float] | int | float:
    """Updates data values to reflect the given unit conversion.

    Handles units in short scientific notation (e.g. m³/h, kW, and ºC), as well as three special units to convert from:
    - from_unit="datetime"          (with data point such as "2023-05-02", "2023-05-02 05:14:49" or "2023-05-02 05:14:49 +02:00")
    - from_unit="dayfirst datetime" (with data point such as "02-05-2023")
    - from_unit="timedelta"         (with data point such as "0 days 01:18:25")
    """
    if from_unit in ("datetime", "dayfirst datetime", "timedelta"):
        return _convert_time_units(data, from_unit, to_unit)

    if from_unit != to_unit:
        from_magnitudes = (
            data.to_numpy()
            if isinstance(data, pd.Series)
            else np.asarray(data) if isinstance(data, list) else np.array([data])
        )
        try:
            from_quantities = ur.Quantity(from_magnitudes, from_unit)
        except ValueError as e:
            # Catch units like "-W" and "100km"
            if str(e) == "Unit expression cannot have a scaling factor.":
                from_quantities = ur.Quantity(from_unit) * from_magnitudes
            else:
                raise e  # reraise
        try:
            to_magnitudes = from_quantities.to(ur.Quantity(to_unit)).magnitude
        except pint.errors.DimensionalityError as e:
            # Catch multiplicative conversions that rely on a capacity, like "%" to "kWh" and vice versa
            if "from 'percent'" in str(e):
                to_magnitudes = (
                    (from_quantities * ur.Quantity(capacity))
                    .to(ur.Quantity(to_unit))
                    .magnitude
                )
            elif "to 'percent'" in str(e):
                to_magnitudes = (
                    (from_quantities / ur.Quantity(capacity))
                    .to(ur.Quantity(to_unit))
                    .magnitude
                )
            else:
                # Catch multiplicative conversions that use the resolution, like "kWh/15min" to "kW"
                if event_resolution is None and isinstance(data, tb.BeliefsSeries):
                    event_resolution = data.event_resolution
                multiplier = determine_unit_conversion_multiplier(
                    from_unit, to_unit, event_resolution
                )
                to_magnitudes = from_magnitudes * multiplier

        # Output type should match input type
        if isinstance(data, pd.Series):
            # Pandas Series
            data = pd.Series(
                to_magnitudes,
                index=data.index,
                name=data.name,
            )
        elif isinstance(data, list):
            # list
            data = list(to_magnitudes)
        else:
            # int or float
            data = to_magnitudes[0]
    return data
