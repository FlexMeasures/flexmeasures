from typing import List, Optional, Tuple, Union
from datetime import date, datetime, timedelta

from flask import current_app
import pandas as pd
from pandas.tseries.frequencies import to_offset
import numpy as np

from bvp.data.models.markets import Market, Price
from bvp.data.models.planning.exceptions import UnknownPricesException


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


def add_tiny_price_slope(prices: pd.DataFrame, d: float = 10 ** -3) -> pd.DataFrame:
    """Add tiny price slope to represent e.g. inflation as a simple linear price increase.
    This is meant to break ties, when multiple time slots have equal prices, in favour of acting sooner.
    We penalise the future with at most d times the price spread (1 per thousand by default).
    """
    price_spread = prices["y"].max() - prices["y"].min()
    if price_spread > 0:
        max_penalty = price_spread * d
    else:
        max_penalty = d
    prices["y"] = prices["y"] + np.linspace(0, max_penalty, prices.size)
    return prices


def get_prices(
    market: Market,
    query_window: Tuple[datetime, datetime],
    resolution: timedelta,
    allow_trimmed_query_window: bool = True,
):
    """Check for known prices or price forecasts, trimming query window accordingly if allowed.
    todo: set a horizon to avoid collecting prices that are not known at the time of constructing the schedule
          (this may require implementing a belief time for scheduling jobs).
    """
    prices = Price.collect(
        market.name,
        query_window=query_window,
        resolution=to_offset(resolution).freqstr,
        create_if_empty=True,
    )
    nan_prices = prices.isnull().values
    if nan_prices.all():
        raise UnknownPricesException("Prices unknown for planning window.")
    elif nan_prices.any():
        if allow_trimmed_query_window:
            query_window = (
                prices.first_valid_index(),
                prices.last_valid_index() + resolution,
            )
            current_app.logger.warning(
                f"Prices partially unknown for planning window. Trimming planning window to {query_window[0]} until {query_window[-1]}."
            )
        else:
            raise UnknownPricesException(
                "Prices partially unknown for planning window."
            )
    return prices, query_window
