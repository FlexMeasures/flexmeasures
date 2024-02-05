from __future__ import annotations

from packaging import version
from typing import List, Optional, Tuple, Union
from datetime import date, datetime, timedelta

from flask import current_app
import pandas as pd
from pandas.tseries.frequencies import to_offset
import numpy as np
import timely_beliefs as tb

from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.planning.exceptions import (
    UnknownMarketException,
    UnknownPricesException,
)
from flexmeasures import Asset
from flexmeasures.data.queries.utils import simplify_index

from flexmeasures.utils.unit_utils import ur, convert_units
from pint.errors import UndefinedUnitError, DimensionalityError


def initialize_df(
    columns: List[str],
    start: datetime,
    end: datetime,
    resolution: timedelta,
    inclusive: str = "left",
) -> pd.DataFrame:
    df = pd.DataFrame(
        index=initialize_index(start, end, resolution, inclusive), columns=columns
    )
    return df


def initialize_series(
    data: Optional[Union[pd.Series, List[float], np.ndarray, float]],
    start: datetime,
    end: datetime,
    resolution: timedelta,
    inclusive: str = "left",
) -> pd.Series:
    s = pd.Series(index=initialize_index(start, end, resolution, inclusive), data=data)
    return s


def initialize_index(
    start: Union[date, datetime, str],
    end: Union[date, datetime, str],
    resolution: Union[timedelta, str],
    inclusive: str = "left",
) -> pd.DatetimeIndex:
    if version.parse(pd.__version__) >= version.parse("1.4.0"):
        return pd.date_range(
            start=start,
            end=end,
            freq=to_offset(resolution),
            inclusive=inclusive,
            name="datetime",
        )
    else:
        return pd.date_range(
            start=start,
            end=end,
            freq=to_offset(resolution),
            closed=inclusive,
            name="datetime",
        )


def add_tiny_price_slope(
    prices: pd.DataFrame, col_name: str = "event_value", d: float = 10**-3
) -> pd.DataFrame:
    """Add tiny price slope to col_name to represent e.g. inflation as a simple linear price increase.
    This is meant to break ties, when multiple time slots have equal prices, in favour of acting sooner.
    We penalise the future with at most d times the price spread (1 per thousand by default).
    """
    price_spread = prices[col_name].max() - prices[col_name].min()
    if price_spread > 0:
        max_penalty = price_spread * d
    else:
        max_penalty = d
    prices[col_name] = prices[col_name] + np.linspace(
        0, max_penalty, prices[col_name].size
    )
    return prices


def get_market(sensor: Sensor) -> Sensor:
    """Get market sensor from the sensor's attributes."""
    price_sensor = Sensor.query.get(sensor.get_attribute("market_id"))
    if price_sensor is None:
        raise UnknownMarketException
    return price_sensor


def get_prices(
    query_window: Tuple[datetime, datetime],
    resolution: timedelta,
    beliefs_before: Optional[datetime],
    price_sensor: Optional[Sensor] = None,
    sensor: Optional[Sensor] = None,
    allow_trimmed_query_window: bool = True,
) -> Tuple[pd.DataFrame, Tuple[datetime, datetime]]:
    """Check for known prices or price forecasts.

    If so allowed, the query window is trimmed according to the available data.
    If not allowed, prices are extended to the edges of the query window:
    - The first available price serves as a naive backcast.
    - The last available price serves as a naive forecast.
    """

    # Look for the applicable price sensor
    if price_sensor is None:
        if sensor is None:
            raise UnknownMarketException(
                "Missing price sensor cannot be derived from a missing sensor"
            )
        price_sensor = get_market(sensor)

    price_bdf: tb.BeliefsDataFrame = TimedBelief.search(
        price_sensor,
        event_starts_after=query_window[0],
        event_ends_before=query_window[1],
        resolution=to_offset(resolution).freqstr,
        beliefs_before=beliefs_before,
        most_recent_beliefs_only=True,
        one_deterministic_belief_per_event=True,
    )
    price_df = simplify_index(price_bdf)
    nan_prices = price_df.isnull().values
    if nan_prices.all() or price_df.empty:
        raise UnknownPricesException(
            f"Prices unknown for planning window. (sensor {price_sensor.id})"
        )
    elif (
        nan_prices.any()
        or pd.Timestamp(price_df.index[0]).tz_convert("UTC")
        != pd.Timestamp(query_window[0]).tz_convert("UTC")
        or pd.Timestamp(price_df.index[-1]).tz_convert("UTC") + resolution
        != pd.Timestamp(query_window[-1]).tz_convert("UTC")
    ):
        if allow_trimmed_query_window:
            first_event_start = price_df.first_valid_index()
            last_event_end = price_df.last_valid_index() + resolution
            current_app.logger.warning(
                f"Prices partially unknown for planning window (sensor {price_sensor.id}). "
                f"Trimming planning window (from {query_window[0]} until {query_window[-1]}) to {first_event_start} until {last_event_end}."
            )
            query_window = (first_event_start, last_event_end)
        else:
            current_app.logger.warning(
                f"Prices partially unknown for planning window (sensor {price_sensor.id}). "
                f"Assuming the first price is valid from the start of the planning window ({query_window[0]}), "
                f"and the last price is valid until the end of the planning window ({query_window[-1]})."
            )
            index = initialize_index(
                start=query_window[0],
                end=query_window[1],
                resolution=resolution,
            )
            price_df = price_df.reindex(index)
            # or to also forward fill intermediate NaN values, use: price_df = price_df.ffill().bfill()
            price_df[: price_df.first_valid_index()] = price_df[
                price_df.index == price_df.first_valid_index()
            ].values[0]
            price_df[price_df.last_valid_index() :] = price_df[
                price_df.index == price_df.last_valid_index()
            ].values[0]
    return price_df, query_window


def get_power_values(
    query_window: Tuple[datetime, datetime],
    resolution: timedelta,
    beliefs_before: Optional[datetime],
    sensor: Sensor,
) -> np.ndarray:
    """Get measurements or forecasts of an inflexible device represented by a power sensor.

    If the requested schedule lies in the future, the returned data will consist of (the most recent) forecasts (if any exist).
    If the requested schedule lies in the past, the returned data will consist of (the most recent) measurements (if any exist).
    The latter amounts to answering "What if we could have scheduled under perfect foresight?".

    :param query_window:    datetime window within which events occur (equal to the scheduling window)
    :param resolution:      timedelta used to resample the forecasts to the resolution of the schedule
    :param beliefs_before:  datetime used to indicate we are interested in the state of knowledge at that time
    :param sensor:          power sensor representing an energy flow out of the device
    :returns:               power measurements or forecasts (consumption is positive, production is negative)
    """
    bdf: tb.BeliefsDataFrame = TimedBelief.search(
        sensor,
        event_starts_after=query_window[0],
        event_ends_before=query_window[1],
        resolution=to_offset(resolution).freqstr,
        beliefs_before=beliefs_before,
        most_recent_beliefs_only=True,
        one_deterministic_belief_per_event=True,
    )  # consumption is negative, production is positive
    df = simplify_index(bdf)
    df = df.reindex(initialize_index(query_window[0], query_window[1], resolution))
    nan_values = df.isnull().values
    if nan_values.any() or df.empty:
        current_app.logger.warning(
            f"Assuming zero power values for (partially) unknown power values for planning window. (sensor {sensor.id})"
        )
        df = df.fillna(0)

    if sensor.get_attribute(
        "consumption_is_positive", False
    ):  # FlexMeasures default is to store consumption as negative power values
        return df.values

    return -df.values


def fallback_charging_policy(
    sensor: Sensor,
    device_constraints: pd.DataFrame,
    start: datetime,
    end: datetime,
    resolution: timedelta,
) -> pd.Series:
    """This fallback charging policy is to just start charging or discharging, or do neither,
    depending on the first target state of charge and the capabilities of the Charge Point.
    Note that this ignores any cause of the infeasibility and,
    while probably a decent policy for Charge Points,
    should not be considered a robust policy for other asset types.
    """
    charge_power = (
        sensor.get_attribute("capacity_in_mw")
        if sensor.get_attribute("is_consumer")
        else 0
    )
    discharge_power = (
        -sensor.get_attribute("capacity_in_mw")
        if sensor.get_attribute("is_producer")
        else 0
    )

    charge_schedule = initialize_series(charge_power, start, end, resolution)
    discharge_schedule = initialize_series(discharge_power, start, end, resolution)
    idle_schedule = initialize_series(0, start, end, resolution)
    if (
        device_constraints["equals"].first_valid_index() is not None
        and device_constraints["equals"][
            device_constraints["equals"].first_valid_index()
        ]
        > 0
    ):
        # start charging to get as close as possible to the next target
        return idle_after_reaching_target(charge_schedule, device_constraints["equals"])
    if (
        device_constraints["equals"].first_valid_index() is not None
        and device_constraints["equals"][
            device_constraints["equals"].first_valid_index()
        ]
        < 0
    ):
        # start discharging to get as close as possible to the next target
        return idle_after_reaching_target(
            discharge_schedule, device_constraints["equals"]
        )
    if (
        device_constraints["max"].first_valid_index() is not None
        and device_constraints["max"][device_constraints["max"].first_valid_index()] < 0
    ):
        # start discharging to try and bring back the soc below the next max constraint
        return idle_after_reaching_target(discharge_schedule, device_constraints["max"])
    if (
        device_constraints["min"].first_valid_index() is not None
        and device_constraints["min"][device_constraints["min"].first_valid_index()] > 0
    ):
        # start charging to try and bring back the soc above the next min constraint
        return idle_after_reaching_target(charge_schedule, device_constraints["min"])
    # stand idle
    return idle_schedule


def idle_after_reaching_target(
    schedule: pd.Series,
    target: pd.Series,
    initial_state: float = 0,
) -> pd.Series:
    """Stop planned (dis)charging after target is reached (or constraint is met)."""
    first_target = target[target.first_valid_index()]
    if first_target > initial_state:
        schedule[schedule.cumsum() > first_target] = 0
    else:
        schedule[schedule.cumsum() < first_target] = 0
    return schedule


def get_quantity_from_attribute(
    entity: Asset | Sensor,
    attribute: str,
    unit: str | ur.Quantity,
) -> ur.Quantity:
    """Get the value (in the given unit) of a quantity stored as an entity attribute.

    :param entity:      The entity (sensor or asset) containing the attribute to retrieve the value from.
    :param attribute:   The attribute name to extract the value from.
    :param unit:        The unit in which the value should be returned.
    :return:            The retrieved quantity or the provided default.
    """
    # Get the default value from the entity attribute
    value: str | float | int = entity.get_attribute(attribute, np.nan)

    # Try to convert it to a quantity in the desired unit
    try:
        q = ur.Quantity(value)
        q = q.to(unit)
    except (UndefinedUnitError, DimensionalityError, ValueError, AssertionError):
        current_app.logger.warning(f"Couldn't convert {value} to `{unit}`")
        q = np.nan * ur.Quantity(unit)  # at least return result in the desired unit
    return q


def get_series_from_quantity_or_sensor(
    quantity_or_sensor: Sensor | ur.Quantity,
    unit: ur.Quantity | str,
    query_window: tuple[datetime, datetime],
    resolution: timedelta,
    beliefs_before: datetime | None = None,
) -> pd.Series:
    """
    Get a time series given a quantity or sensor defined on a time window.

    :param quantity_or_sensor:  pint Quantity or timely-beliefs Sensor, measuring e.g. power capacity or efficiency
    :param unit:                unit of the output data.
    :param query_window:        tuple representing the start and end of the requested data
    :param resolution:          time resolution of the requested data
    :param beliefs_before:      optional datetime used to indicate we are interested in the state of knowledge at that time
    :return:                    pandas Series with the requested time series data
    """

    start, end = query_window
    index = initialize_index(start=start, end=end, resolution=resolution)

    if isinstance(quantity_or_sensor, ur.Quantity):
        if np.isnan(quantity_or_sensor.magnitude):
            magnitude = np.nan
        else:
            magnitude = quantity_or_sensor.to(unit).magnitude
        time_series = pd.Series(magnitude, index=index)
    elif isinstance(quantity_or_sensor, Sensor):
        bdf: tb.BeliefsDataFrame = TimedBelief.search(
            quantity_or_sensor,
            event_starts_after=query_window[0],
            event_ends_before=query_window[1],
            resolution=resolution,
            beliefs_before=beliefs_before,
            most_recent_beliefs_only=True,
            one_deterministic_belief_per_event=True,
        )
        time_series = simplify_index(bdf).reindex(index).squeeze()
        time_series = convert_units(time_series, quantity_or_sensor.unit, unit)
    else:
        raise TypeError(
            f"quantity_or_sensor {quantity_or_sensor} should be a pint Quantity or timely-beliefs Sensor"
        )

    return time_series


def get_continuous_series_sensor_or_quantity(
    quantity_or_sensor: Sensor | ur.Quantity | None,
    actuator: Sensor | Asset,
    unit: ur.Quantity | str,
    query_window: tuple[datetime, datetime],
    resolution: timedelta,
    beliefs_before: datetime | None = None,
    fallback_attribute: str | None = None,
    max_value: float | int = np.nan,
) -> pd.Series:
    """Creates a time series from a quantity or sensor within a specified window,
    falling back to a given `fallback_attribute` and making sure no values exceed `max_value`.

    :param quantity_or_sensor:      The quantity or sensor containing the data.
    :param actuator:                The actuator from which relevant defaults are retrieved.
    :param unit:                    The desired unit of the data.
    :param query_window:            The time window (start, end) to query the data.
    :param resolution:              The resolution or time interval for the data.
    :param beliefs_before:          Timestamp for prior beliefs or knowledge.
    :param fallback_attribute:      Attribute serving as a fallback default in case no quantity or sensor is given.
    :param max_value:               Maximum value (also replacing NaN values).
    :returns:                       time series data with missing values handled based on the chosen method.
    """
    if quantity_or_sensor is None:
        quantity_or_sensor = get_quantity_from_attribute(
            entity=actuator,
            attribute=fallback_attribute,
            unit=unit,
        )

    time_series = get_series_from_quantity_or_sensor(
        quantity_or_sensor=quantity_or_sensor,
        unit=unit,
        query_window=query_window,
        resolution=resolution,
        beliefs_before=beliefs_before,
    )

    # Apply upper limit
    time_series = nanmin_of_series_and_value(time_series, max_value)

    return time_series


def nanmin_of_series_and_value(s: pd.Series, value: float) -> pd.Series:
    """Perform a nanmin between a Series and a float."""
    return s.fillna(value).clip(upper=value)
