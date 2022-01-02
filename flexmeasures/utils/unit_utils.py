from datetime import timedelta
from typing import Optional

from moneyed import list_all_currencies
import importlib.resources as pkg_resources
import pint

# Edit constants template to stop using h to represent planck_constant
constants_template = (
    pkg_resources.read_text(pint, "constants_en.txt")
    .replace("= h  ", "     ")
    .replace(" h ", " planck_constant ")
)

# Edit units template to use h to represent hour instead of planck_constant
units_template = (
    pkg_resources.read_text(pint, "default_en.txt")
    .replace("@import constants_en.txt", "")
    .replace(" h ", " planck_constant ")
    .replace("hour = 60 * minute = hr", "hour = 60 * minute = h = hr")
)

# Create custom template
custom_template = [f"{c} = [currency_{c}]" for c in list_all_currencies()]

# Join templates as iterable object
full_template = (
    constants_template.split("\n") + units_template.split("\n") + custom_template
)

# Set up UnitRegistry with abbreviated scientific format
ur = pint.UnitRegistry(full_template)
ur.default_format = "~P"  # short pretty


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
]  # todo: move to config setting, with these as a default (NB prefixes do not matter here, this is about SI base units, so km/h is equivalent to m/h)
PREFERRED_UNITS_DICT = dict(
    [(ur.parse_expression(x).dimensionality, x) for x in PREFERRED_UNITS]
)


def to_preferred(x: pint.Quantity) -> pint.Quantity:
    """From https://github.com/hgrecco/pint/issues/676#issuecomment-689157693"""
    dim = x.dimensionality
    if dim in PREFERRED_UNITS_DICT:
        return x.to(PREFERRED_UNITS_DICT[dim]).to_compact()
    return x


def is_valid_unit(unit: str) -> bool:
    """Return True if the pint library can work with this unit identifier."""
    try:
        ur.Quantity(unit)
    except ValueError:
        return False
    except pint.errors.UndefinedUnitError:
        return False
    return True


def determine_unit_conversion_multiplier(
    from_unit: str, to_unit: str, duration: Optional[timedelta] = None
):
    """Determine the value multiplier for a given unit conversion.
    If needed, requires a duration to convert from units of stock change to units of flow.
    """
    scalar = (
        ur.Quantity(from_unit).to_base_units() / ur.Quantity(to_unit).to_base_units()
    )
    if scalar.dimensionality == ur.Quantity("h").dimensionality:
        if duration is None:
            raise ValueError(
                f"Cannot convert units from {from_unit} to {to_unit} without known duration."
            )
        return scalar.to_timedelta() / duration
    return scalar.to_reduced_units().magnitude


def determine_flow_unit(stock_unit: str, time_unit: str = "h"):
    """For example:
    >>> determine_flow_unit("m³")  # m³/h
    >>> determine_flow_unit("kWh")  # kW
    """
    flow = to_preferred(ur.Quantity(stock_unit) / ur.Quantity(time_unit))
    return "{:~P}".format(flow.units)


def determine_stock_unit(flow_unit: str, time_unit: str = "h"):
    """For example:
    >>> determine_stock_unit("m³/h")  # m³
    >>> determine_stock_unit("kW")  # kWh
    """
    stock = to_preferred(ur.Quantity(flow_unit) * ur.Quantity(time_unit))
    return "{:~P}".format(stock.units)


def units_are_convertible(
    from_unit: str, to_unit: str, duration_known: bool = True
) -> bool:
    """For example, a sensor with W units allows data to be posted with units:
    >>> units_are_convertible("kW", "W")  # True (units just have different prefixes)
    >>> units_are_convertible("J/s", "W")  # True (units can be converted using some multiplier)
    >>> units_are_convertible("Wh", "W")  # True (units that represent a stock delta can, knowing the duration, be converted to a flow)
    >>> units_are_convertible("°C", "W")  # False
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
    >>> is_power_unit("kW")  # True
    >>> is_power_unit("°C")  # False
    >>> is_power_unit("kWh")  # False
    >>> is_power_unit("EUR/MWh")  # False
    """
    if not is_valid_unit(unit):
        return False
    return ur.Quantity(unit).dimensionality == ur.Quantity("W").dimensionality


def is_energy_unit(unit: str) -> bool:
    """For example:
    >>> is_energy_unit("kW")  # False
    >>> is_energy_unit("°C")  # False
    >>> is_energy_unit("kWh")  # True
    >>> is_energy_unit("EUR/MWh")  # False
    """
    if not is_valid_unit(unit):
        return False
    return ur.Quantity(unit).dimensionality == ur.Quantity("Wh").dimensionality
