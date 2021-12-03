from typing import List, Optional, Type, Tuple, Union
from datetime import date, datetime, timedelta

from flask import current_app
import pandas as pd
from pandas.tseries.frequencies import to_offset
import numpy as np
import timely_beliefs as tb

from flexmeasures.data.models.markets import Market, Price
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.planning.exceptions import (
    MissingAttributeException,
    UnknownMarketException,
    UnknownPricesException,
    WrongTypeAttributeException,
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


def get_market(sensor: Sensor) -> Market:
    market = Market.query.get(sensor.get_attribute("market_id"))
    if market is None:
        raise UnknownMarketException
    return market


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

    # Look for the applicable market
    market = get_market(sensor)

    price_bdf: tb.BeliefsDataFrame = Price.collect(
        market.name,
        query_window=query_window,
        resolution=to_offset(resolution).freqstr,
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


def check_required_attributes(
    sensor: Sensor,
    attributes: List[Union[str, Tuple[str, Union[Type, Tuple[Type, ...]]]]],
):
    """Raises if any attribute in the list of attributes is missing on the Sensor, or has the wrong type.

    :param sensor: Sensor object to check for attributes
    :param attributes: List of either an attribute name or a tuple of an attribute name and its allowed type
                       (the allowed type may also be a tuple of several allowed types)
    """
    missing_attributes: List[str] = []
    wrong_type_attributes: List[Tuple[str, Type, Type]] = []
    for attribute_field in attributes:
        if isinstance(attribute_field, str):
            attribute_name = attribute_field
            expected_attribute_type = None
        elif isinstance(attribute_field, tuple) and len(attribute_field) == 2:
            attribute_name = attribute_field[0]
            expected_attribute_type = attribute_field[1]
        else:
            raise ValueError("Unexpected declaration of attributes")

        # Check attribute exists
        if not sensor.has_attribute(attribute_name):
            missing_attributes.append(attribute_name)

        # Check attribute is of the expected type
        if expected_attribute_type is not None:
            attribute = sensor.get_attribute(attribute_name)
            if not isinstance(attribute, expected_attribute_type):
                wrong_type_attributes.append(
                    (attribute_name, type(attribute), expected_attribute_type)
                )
    if missing_attributes:
        raise MissingAttributeException(
            f"Sensor is missing required attributes: {', '.join(missing_attributes)}"
        )
    if wrong_type_attributes:
        error_message = ""
        for (
            attribute_name,
            attribute_type,
            expected_attribute_type,
        ) in wrong_type_attributes:
            error_message += f"- attribute '{attribute_name}' is a {attribute_type} instead of a {expected_attribute_type}\n"
        raise WrongTypeAttributeException(
            f"Sensor attributes are not of the required type:\n {error_message}"
        )
