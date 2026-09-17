"""Utility module for bounding values: snapping them into intervals and clipping them to a range.

The same ``lower``, ``upper`` and ``snap`` settings shape a forecaster's output,
and clean the readings a data generator takes from a referenced sensor.
Bounds are given as numbers or quantity strings, and are read in the unit of the sensor they apply to.
"""

from __future__ import annotations

import math
import numbers
from typing import Any

import numpy as np

from flexmeasures.utils.unit_utils import (
    QUANTITY_PARSE_ERRORS,
    is_parseable_quantity,
    units_are_convertible,
    ur,
)


def _is_unitless(unit: str | None) -> bool:
    """Check whether a parsed quantity carries no physical unit."""
    return unit in (None, "", "dimensionless")


def _quantity_to_sensor_value(
    value: Any, sensor_unit: str, label: str = "Forecast post-processing"
) -> float:
    """Parse a configured quantity and return its magnitude in the sensor unit."""
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        return float(value)

    if not isinstance(value, str):
        raise ValueError(
            f"Bounds must be numbers or quantity strings, not {type(value).__name__} ({label})."
        )

    try:
        quantity = ur.Quantity(value)
    except QUANTITY_PARSE_ERRORS as exc:
        raise ValueError(f"Could not parse the value '{value}' ({label}).") from exc

    from_unit = f"{quantity.units:~P}"
    if _is_unitless(from_unit):
        return float(quantity.magnitude)

    to_unit = sensor_unit or "dimensionless"
    if not units_are_convertible(from_unit, to_unit, duration_known=False):
        raise ValueError(
            f"Could not convert the value '{value}' to '{sensor_unit}' ({label})."
        )
    return float(quantity.to(to_unit).magnitude)


def _parse_snap_intervals(
    snap: dict, sensor_unit: str, label: str = "Forecast post-processing"
) -> list[tuple[float, float, float]]:
    """Validate and parse a snap mapping into ``(target, first, second)`` triples.

    Each value that falls inside an interval is replaced by a target that must lie within that interval (on a bound or inside it),
    so values never snap to a value outside their interval.
    The first boundary is treated as inclusive and the second as exclusive,
    so listing the boundaries in reverse order flips which side is closed (``["4 kW", "10 kW"]`` means ``[4, 10)`` while ``["10 kW", "4 kW"]`` means ``(4, 10]``).
    This keeps adjacent intervals unambiguous: a shared boundary belongs to whichever interval opens at it.
    """
    parsed = []
    for target, interval in snap.items():
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise ValueError(f"{label} snap intervals must contain exactly two bounds.")

        target_value = _quantity_to_sensor_value(target, sensor_unit, label)
        first = _quantity_to_sensor_value(interval[0], sensor_unit, label)
        second = _quantity_to_sensor_value(interval[1], sensor_unit, label)
        if math.isclose(first, second):
            raise ValueError(f"{label} snap interval bounds must differ.")
        if not min(first, second) <= target_value <= max(first, second):
            raise ValueError(
                f"The snap target must lie within its interval bounds ({label})."
            )
        parsed.append((target_value, first, second))
    return parsed


def parse_bounds(
    lower: Any,
    upper: Any,
    snap: dict | None,
    sensor_unit: str,
    label: str = "Forecast post-processing",
) -> tuple[float | None, float | None, list[tuple[float, float, float]]]:
    """Parse configured bounds into plain magnitudes in the sensor unit.

    :param lower:       Optional lower bound, as a number or a quantity string.
    :param upper:       Optional upper bound, as a number or a quantity string.
    :param snap:        Optional mapping from snap targets to two-bound intervals.
    :param sensor_unit: Unit the bounds are converted into.
    :param label:       Suffix for error messages, naming what is being bounded.
    :returns:           ``(lower_value, upper_value, snap_intervals)``, ready for :func:`apply_bounds_to_values`.
    :raises ValueError: If a bound cannot be parsed, cannot be converted to the sensor unit, or contradicts another bound.
    """
    lower_value = (
        _quantity_to_sensor_value(lower, sensor_unit, label)
        if lower is not None
        else None
    )
    upper_value = (
        _quantity_to_sensor_value(upper, sensor_unit, label)
        if upper is not None
        else None
    )
    if (
        lower_value is not None
        and upper_value is not None
        and lower_value > upper_value
    ):
        raise ValueError(
            f"The lower bound cannot be greater than the upper bound ({label})."
        )
    snap_intervals = _parse_snap_intervals(snap or {}, sensor_unit, label)
    return lower_value, upper_value, snap_intervals


def _unparseable_bound_errors(
    lower: Any, upper: Any, snap: dict | None
) -> dict[str, list[str]]:
    """Collect, per bound, which bounds cannot be read as quantities at all."""
    errors: dict[str, list[str]] = {}
    for field_name, value in (("lower", lower), ("upper", upper)):
        if value is not None and not is_parseable_quantity(value):
            errors[field_name] = [
                "Must be a number or a parseable quantity string (e.g. 0 or '0 kW')."
            ]

    if snap is not None and not isinstance(snap, dict):
        errors["snap"] = ["Must be a mapping from snap targets to intervals."]
        return errors
    snap_errors = []
    for target, interval in (snap or {}).items():
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            snap_errors.append(
                f"Snap entry '{target}' must map to an interval of exactly two bounds."
            )
        elif not all(is_parseable_quantity(v) for v in (target, *interval)):
            snap_errors.append(
                f"Snap entry '{target}' must use numbers or parseable quantity strings."
            )
    if snap_errors:
        errors["snap"] = snap_errors
    return errors


def _inapplicable_bound_errors(
    lower: Any, upper: Any, snap: dict | None, sensor_unit: str, label: str
) -> dict[str, list[str]]:
    """Collect, per bound, which readable bounds still cannot be applied in the sensor's unit."""
    errors: dict[str, list[str]] = {}
    for field_name, value in (("lower", lower), ("upper", upper)):
        if value is None:
            continue
        try:
            _quantity_to_sensor_value(value, sensor_unit, label)
        except ValueError as exc:
            errors[field_name] = [str(exc)]
    try:
        _parse_snap_intervals(snap or {}, sensor_unit, label)
    except ValueError as exc:
        errors["snap"] = [str(exc)]

    if not errors:
        try:
            parse_bounds(lower, upper, snap, sensor_unit, label)
        except ValueError as exc:
            errors["lower"] = [str(exc)]
    return errors


def bound_validation_errors(
    lower: Any,
    upper: Any,
    snap: dict | None,
    sensor_unit: str | None = None,
    label: str = "Forecast post-processing",
) -> dict[str, list[str]]:
    """Collect what is wrong with configured bounds, per bound, for a schema to report.

    Without a sensor unit, only whether each bound can be read as a quantity is checked.
    With one, the bounds are also parsed in full, so a bound in an incompatible unit,
    a snap target outside its interval and a lower bound above the upper bound are caught too.

    :param lower:       Optional lower bound, as a number or a quantity string.
    :param upper:       Optional upper bound, as a number or a quantity string.
    :param snap:        Optional mapping from snap targets to two-bound intervals.
    :param sensor_unit: Unit of the sensor the bounds apply to, if already known.
    :param label:       Suffix for error messages, naming what is being bounded.
    :returns:           Error messages per bound name (``lower``, ``upper`` or ``snap``), empty if the bounds are valid.
    """
    errors = _unparseable_bound_errors(lower, upper, snap)
    if errors or sensor_unit is None:
        return errors
    return _inapplicable_bound_errors(lower, upper, snap, sensor_unit, label)


def apply_bounds_to_values(
    values: np.ndarray,
    lower_value: float | None,
    upper_value: float | None,
    snap_intervals: list[tuple[float, float, float]],
) -> np.ndarray:
    """Snap and then clip an array of values, returning a new array.

    Snapping runs first, against the unmodified values, so intervals cannot cascade into each other.
    Clipping runs afterwards and always takes precedence, so a snap target outside the bounds is still clipped back into range.
    NaN values are left alone by both steps.

    :param values:         The values to bound.
    :param lower_value:    Lower clip bound in the same unit, or None to leave the lower side unbounded.
    :param upper_value:    Upper clip bound in the same unit, or None to leave the upper side unbounded.
    :param snap_intervals: ``(target, first, second)`` triples, as parsed by :func:`parse_bounds`.
    :returns:              A new array of bounded values.
    """
    original = np.asarray(values, dtype=float)
    bounded = original.copy()
    for target_value, first, second in snap_intervals:
        if first <= second:
            # First bound inclusive, second exclusive: [first, second).
            mask = (original >= first) & (original < second)
        else:
            # Reversed order flips the closed side: (second, first].
            mask = (original > second) & (original <= first)
        bounded[mask] = target_value
    if lower_value is not None or upper_value is not None:
        bounded = np.clip(bounded, lower_value, upper_value)
    return bounded
