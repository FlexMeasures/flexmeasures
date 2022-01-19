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
from flexmeasures.data.queries.utils import simplify_index


def initialize_df(
    columns: List[str], start: datetime, end: datetime, resolution: timedelta
) -> pd.DataFrame:
    df = pd.DataFrame(index=initialize_index(start, end, resolution), columns=columns)
    return df


def initialize_series(
    data: Optional[Union[pd.Series, List[float], np.ndarray, float]],
    start: datetime,
    end: datetime,
    resolution: timedelta,
) -> pd.Series:
    s = pd.Series(index=initialize_index(start, end, resolution), data=data)
    return s


def initialize_index(
    start: Union[date, datetime], end: Union[date, datetime], resolution: timedelta
) -> pd.DatetimeIndex:
    i = pd.date_range(
        start=start, end=end, freq=to_offset(resolution), closed="left", name="datetime"
    )
    return i


def add_tiny_price_slope(
    prices: pd.DataFrame, col_name: str = "event_value", d: float = 10 ** -3
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
    sensor = Sensor.query.get(sensor.get_attribute("market_id"))
    if sensor is None:
        raise UnknownMarketException
    return sensor


def get_prices(
    sensor: Sensor,
    query_window: Tuple[datetime, datetime],
    resolution: timedelta,
    allow_trimmed_query_window: bool = True,
) -> Tuple[pd.DataFrame, Tuple[datetime, datetime]]:
    """Check for known prices or price forecasts, trimming query window accordingly if allowed.
    todo: set a horizon to avoid collecting prices that are not known at the time of constructing the schedule
          (this may require implementing a belief time for scheduling jobs).
    """

    # Look for the applicable market sensor
    sensor = get_market(sensor)

    price_bdf: tb.BeliefsDataFrame = TimedBelief.search(
        sensor.name,
        event_starts_after=query_window[0],
        event_ends_before=query_window[1],
        resolution=to_offset(resolution).freqstr,
        most_recent_beliefs_only=True,
        one_deterministic_belief_per_event=True,
    )
    price_df = simplify_index(price_bdf)
    nan_prices = price_df.isnull().values
    if nan_prices.all() or price_df.empty:
        raise UnknownPricesException("Prices unknown for planning window.")
    elif (
        nan_prices.any()
        or pd.Timestamp(price_df.index[0]).tz_convert("UTC")
        != pd.Timestamp(query_window[0]).tz_convert("UTC")
        or pd.Timestamp(price_df.index[-1]).tz_convert("UTC")
        != pd.Timestamp(query_window[-1]).tz_convert("UTC")
    ):
        if allow_trimmed_query_window:
            first_event_start = price_df.first_valid_index()
            last_event_end = price_df.last_valid_index() + resolution
            current_app.logger.warning(
                f"Prices partially unknown for planning window. Trimming planning window (from {query_window[0]} until {query_window[-1]}) to {first_event_start} until {last_event_end}."
            )
            query_window = (first_event_start, last_event_end)
        else:
            raise UnknownPricesException(
                "Prices partially unknown for planning window."
            )
    return price_df, query_window


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
