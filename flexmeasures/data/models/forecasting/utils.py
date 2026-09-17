from __future__ import annotations

import math
import numbers
from typing import Any

import numpy as np
import pandas as pd
import timely_beliefs as tb
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.sensors import SensorReference

from datetime import datetime, timedelta

from flexmeasures.data import db
from flexmeasures.utils.unit_utils import units_are_convertible, ur


def negative_to_zero(x: np.ndarray) -> np.ndarray:
    return np.where(x < 0, 0, x)


def _is_unitless(unit: str | None) -> bool:
    """Check whether a parsed quantity carries no physical unit."""
    return unit in (None, "", "dimensionless")


def _is_parseable_quantity(value: Any) -> bool:
    """Whether a configured bound is a number or a pint-parseable quantity string."""
    if isinstance(value, numbers.Real):
        return True
    if not isinstance(value, str):
        return False
    try:
        ur.Quantity(value)
    except Exception:
        return False
    return True


def _quantity_to_sensor_value(
    value: Any, sensor_unit: str, label: str = "Forecast post-processing"
) -> float:
    """Parse a configured quantity and return its magnitude in the sensor unit."""
    if isinstance(value, numbers.Real):
        return float(value)

    if not isinstance(value, str):
        raise ValueError(
            f"Bounds must be numbers or quantity strings, not {type(value).__name__} ({label})."
        )

    try:
        quantity = ur.Quantity(value)
    except Exception as exc:
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

    Each value that falls inside an interval is replaced by a target that must lie
    within that interval (on a bound or inside it), so values never snap to a value
    outside their interval. The first boundary is treated as inclusive and the second
    as exclusive, so listing the boundaries in reverse order flips which side is closed
    (``["4 kW", "10 kW"]`` means ``[4, 10)`` while ``["10 kW", "4 kW"]`` means
    ``(4, 10]``). This keeps adjacent intervals unambiguous: a shared boundary belongs
    to whichever interval opens at it.
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
    :param label:       Prefix for error messages, naming what is being bounded.
    :returns:           ``(lower_value, upper_value, snap_intervals)``, ready for :func:`apply_bounds_to_values`.
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


def apply_bounds_to_values(
    values: np.ndarray,
    lower_value: float | None,
    upper_value: float | None,
    snap_intervals: list[tuple[float, float, float]],
) -> np.ndarray:
    """Snap and then clip an array of values, returning a new array.

    Snapping runs first, against the unmodified values, so intervals cannot cascade into each other.
    Clipping runs afterwards and always takes precedence, so a snap target outside the bounds is still clipped back into range.
    Values that are not a number are left alone by both steps.

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


def apply_forecast_post_processing(
    data: pd.DataFrame,
    horizon: int,
    config: dict,
    sensor_unit: str,
) -> pd.DataFrame:
    """Apply configured clipping and snapping to forecast horizon columns.

    Snapping runs first, on the unmodified predictions, so intervals cannot cascade.
    Clipping to ``lower``/``upper`` runs afterwards and always takes precedence, so a
    snap target outside the bounds is still clipped back into range.

    :param data:        DataFrame containing one column per forecast horizon.
    :param horizon:     Maximum forecast horizon in time-steps.
    :param config:      Forecaster config with optional ``lower``, ``upper`` and ``snap`` fields.
    :param sensor_unit: Unit of the sensor to which forecasts will be saved.
    :returns:           A DataFrame with post-processed forecast values.
    """
    lower = config.get("lower")
    upper = config.get("upper")
    snap = config.get("snap") or {}

    if lower is None and upper is None and not snap:
        return data

    processed = data.copy()
    forecast_columns = [f"{h}h" for h in range(1, horizon + 1)]
    lower_value, upper_value, snap_intervals = parse_bounds(
        lower, upper, snap, sensor_unit
    )

    for column in forecast_columns:
        processed[column] = apply_bounds_to_values(
            processed[column].to_numpy(dtype=float),
            lower_value,
            upper_value,
            snap_intervals,
        )
    return processed


def data_to_bdf(
    data: pd.DataFrame,
    horizon: int,
    probabilistic: bool,
    target_sensor: Sensor | SensorReference,
    sensor_to_save: Sensor,
    data_source: DataSource,
) -> tb.BeliefsDataFrame:
    """
    Converts a prediction DataFrame into a BeliefsDataFrame for saving to the database.

    :param data:            DataFrame containing predictions for different forecast horizons.
                            If probabilistic forecasts are generated, `data` includes a `component` column,
                            which encodes which quantile (cumulative probability) the row corresponds to.
    :param horizon:         Maximum forecast horizon in time-steps relative to the sensor's resolution.
                            For example, if the sensor resolution is 1 hour, a horizon of 48 represents
                            a forecast horizon of 48 hours. Similarly, if the sensor resolution is 15 minutes,
                            a horizon of 4*48 represents a forecast horizon of 48 hours.
    :param probabilistic:   Whether the forecasts are probabilistic or deterministic.
    :param target_sensor:   The Sensor object for which the predictions are made, or a source-filtered reference to it.
    :param sensor_to_save:  The Sensor object to save the forecasts to.
    :param data_source:     The DataSource object to attribute the forecasts to.
    :returns:               A formatted BeliefsDataFrame ready for database insertion.
    """
    df = data.copy()
    df.reset_index(inplace=True)

    # Rename target to '0h'
    df = df.rename(columns={f"{target_sensor.name} (ID: {target_sensor.id})": "0h"})
    df["event_start"] = pd.to_datetime(df["event_start"])
    df["belief_time"] = pd.to_datetime(df["belief_time"])

    # Probabilities
    probabilistic_values = (
        [float(x.rsplit("_", 1)[-1]) for x in data.index.get_level_values("component")]
        if probabilistic
        else [0.5] * len(df)
    )

    # Build horizons
    horizons = pd.Series(range(1, horizon + 1), name="h")
    expanded = pd.concat([df.assign(h=h) for h in horizons], ignore_index=True)

    # Add shifted event_starts
    expanded["event_start"] = expanded["event_start"] + expanded["h"].apply(
        lambda h: target_sensor.event_resolution * h
    )

    # Forecast values
    expanded["forecasts"] = expanded.apply(lambda r: r[f"{r.h}h"], axis=1)

    # Probabilities (repeat original values across horizons)
    expanded["cumulative_probability"] = np.repeat(probabilistic_values, horizon)

    # Cleanup
    test_df = expanded[
        ["event_start", "belief_time", "forecasts", "cumulative_probability"]
    ].copy()
    test_df["event_start"] = (
        test_df["event_start"]
        .dt.tz_localize("UTC")
        .dt.tz_convert(target_sensor.timezone)
    )
    test_df["belief_time"] = (
        test_df["belief_time"]
        .dt.tz_localize("UTC")
        .dt.tz_convert(target_sensor.timezone)
    )

    # Build forecast DataFrame
    forecast_df = pd.DataFrame(
        {
            "forecasts": test_df["forecasts"].values,
            "cumulative_probability": test_df["cumulative_probability"].values,
        },
        index=pd.MultiIndex.from_arrays(
            [test_df["event_start"], test_df["belief_time"]],
            names=["event_start", "belief_time"],
        ),
    )

    # # Set up forecaster regressors attributes to be saved on the datasource
    # # use sensor names from the database and id's in attribute
    # # use sensor names from cli command for model name
    #
    # if "autoregressive" in regressors:
    #     regressors_names = "autoregressive"
    # else:
    #     regressors_names = ", ".join(regressors)
    #
    # data_source = get_or_create_source(
    #     source="forecaster",
    #     model=f"CustomLGBM ({regressors_names})",
    #     source_type="forecaster",
    #     attributes=self.data_source.attributes,
    # )
    source = refresh_data_source(data_source)

    # Convert to BeliefsDataFrame
    bdf = tb.BeliefsDataFrame(
        forecast_df.reset_index().rename(columns={"forecasts": "event_value"}),
        source=source,
        sensor=sensor_to_save,
    )
    return bdf


def floor_to_resolution(dt: datetime, resolution: timedelta) -> datetime:
    delta_seconds = resolution.total_seconds()
    floored = dt.timestamp() - (dt.timestamp() % delta_seconds)
    return datetime.fromtimestamp(floored, tz=dt.tzinfo)


def refresh_data_source(data_source: DataSource) -> DataSource:
    """Refresh the potentially detached data source.

    This avoids a sqlalchemy.exc.IntegrityError / psycopg2.errors.ForeignKeyViolation
    for the data source ID not being present in the data_source table.

    Prefer looking up by ID when available: this sidesteps the ``attributes_hash``
    mismatch that arises because PostgreSQL JSONB returns keys in alphabetical order,
    while the stored hash was originally computed from the Python insertion-order dict.
    """

    if data_source.id is not None:
        refreshed = db.session.get(DataSource, data_source.id)
        if refreshed is not None:
            return refreshed

    from flexmeasures.data.services.data_sources import get_or_create_source

    return get_or_create_source(
        data_source.name,
        source_type=data_source.type,
        model=data_source.model,
        version=data_source.version,
        attributes=data_source.attributes,
    )
