""" Various calculations """
from __future__ import annotations

from datetime import timedelta
import math

import numpy as np
import pandas as pd


def mean_absolute_error(y_true: np.ndarray, y_forecast: np.ndarray):
    y_true, y_forecast = drop_nan_rows(y_true, y_forecast)
    if y_true.size == 0 or y_forecast.size == 0:
        return np.nan
    else:
        return np.mean(np.abs((y_true - y_forecast)))


def mean_absolute_percentage_error(y_true: np.ndarray, y_forecast: np.ndarray):
    y_true, y_forecast = drop_nan_rows(y_true, y_forecast)
    if y_true.size == 0 or y_forecast.size == 0 or 0 in y_true:
        return np.nan
    else:
        return np.mean(np.abs((y_true - y_forecast) / y_true))


def weighted_absolute_percentage_error(y_true: np.ndarray, y_forecast: np.ndarray):
    y_true, y_forecast = drop_nan_rows(y_true, y_forecast)
    if y_true.size == 0 or y_forecast.size == 0 or sum(y_true) == 0:
        return np.nan
    else:
        return np.sum(np.abs((y_true - y_forecast))) / np.abs(np.sum(y_true))


def drop_nan_rows(a, b):
    d = np.array(list(zip(a, b)))
    d = d[~np.any(np.isnan(d), axis=1)]
    return d[:, 0], d[:, 1]


def apply_stock_changes_and_losses(
    initial: float,
    changes: list[float],
    storage_efficiency: float | list[float],
    how: str = "linear",
    decimal_precision: int | None = None,
) -> list[float]:
    r"""Assign stock changes and determine losses from storage efficiency.

    The initial stock is exponentially decayed, as with each consecutive (constant-resolution) time step,
    some constant percentage of the previous stock remains. For example:

    .. math::

       100 \rightarrow 90 \rightarrow 81 \rightarrow 72.9 \rightarrow ...

    For computing the decay of the changes, we make an assumption on how a delta :math:`d` is distributed within a given time step.
    In case it happens at a constant rate, this leads to a linear stock change from one time step to the next.

    An :math:`e` is introduced when we apply exponential decay to that.
    To see that, imagine we cut one time step in :math:`n` pieces (each with a stock change :math:`\frac{d}{n}` ),
    apply the efficiency to each piece :math:`k` (for the corresponding fraction of the time step :math:`k/n`),
    and then take the limit :math:`n \rightarrow \infty`:

    .. math::

       \lim_{n \rightarrow \infty} \sum_{k=0}^{n}{\frac{d}{n} \eta^{k/n}}

    `which is <https://www.wolframalpha.com/input?i=Limit%5BSum%5B%5Ceta%5E%28k%2Fn%29%2Fn%2C+%7Bk%2C+0%2C+n%7D%5D%2C+n+-%3E+Infinity%5D&assumption=%22LimitHead%22+-%3E+%7B%22Discrete%22%7D>`_:

    .. math::

       d \cdot \frac{\eta - 1}{e^{\eta}}

    :param initial:             initial stock
    :param changes:             stock change for each step
    :param storage_efficiency:  ratio of stock left after a step (constant ratio or one per step)
    :param how:                 left, right or linear; how stock changes should be applied, which affects how losses are applied
    :param decimal_precision:   Optional decimal precision to round off results (useful for tests failing over machine precision)
    """
    stocks = [initial]
    if not isinstance(storage_efficiency, list):
        storage_efficiency = [storage_efficiency] * len(changes)
    for d, e in zip(changes, storage_efficiency):
        s = stocks[-1]
        if e == 1:
            next_stock = s + d
        elif how == "left":
            # First apply the stock change, then apply the losses (i.e. the stock changes on the left side of the time interval in which the losses apply)
            next_stock = (s + d) * e
        elif how == "right":
            # First apply the losses, then apply the stock change (i.e. the stock changes on the right side of the time interval in which the losses apply)
            next_stock = s * e + d
        elif how == "linear":
            # Assume the change happens at a constant rate, leading to a linear stock change, and exponential decay, within the current interval
            next_stock = s * e + d * (e - 1) / math.log(e)
        else:
            raise NotImplementedError(f"Missing implementation for how='{how}'.")
        stocks.append(next_stock)
    if decimal_precision is not None:
        stocks = [round(s, decimal_precision) for s in stocks]
    return stocks


def integrate_time_series(
    series: pd.Series,
    initial_stock: float,
    up_efficiency: float | pd.Series = 1,
    down_efficiency: float | pd.Series = 1,
    storage_efficiency: float | pd.Series = 1,
    decimal_precision: int | None = None,
) -> pd.Series:
    """Integrate time series of length n and inclusive="left" (representing a flow)
    to a time series of length n+1 and inclusive="both" (representing a stock),
    given an initial stock (i.e. the constant of integration).
    The unit of time is hours: i.e. the stock unit is flow unit times hours (e.g. a flow in kW becomes a stock in kWh).
    Optionally, set a decimal precision to round off the results (useful for tests failing over machine precision).

    >>> s = pd.Series([1, 2, 3, 4], index=pd.date_range(datetime(2001, 1, 1, 5), datetime(2001, 1, 1, 6), freq=timedelta(minutes=15), inclusive="left"))
    >>> integrate_time_series(s, 10)
        2001-01-01 05:00:00    10.00
        2001-01-01 05:15:00    10.25
        2001-01-01 05:30:00    10.75
        2001-01-01 05:45:00    11.50
        2001-01-01 06:00:00    12.50
        Freq: D, dtype: float64

    >>> s = pd.Series([1, 2, 3, 4], index=pd.date_range(datetime(2001, 1, 1, 5), datetime(2001, 1, 1, 7), freq=timedelta(minutes=30), inclusive="left"))
    >>> integrate_time_series(s, 10)
        2001-01-01 05:00:00    10.0
        2001-01-01 05:30:00    10.5
        2001-01-01 06:00:00    11.5
        2001-01-01 06:30:00    13.0
        2001-01-01 07:00:00    15.0
        dtype: float64
    """
    resolution = pd.to_timedelta(series.index.freq)
    storage_efficiency = (
        storage_efficiency
        if isinstance(storage_efficiency, pd.Series)
        else pd.Series(storage_efficiency, index=series.index)
    )

    # Convert from flow to stock change, applying conversion efficiencies
    stock_change = pd.Series(data=np.NaN, index=series.index)
    stock_change.loc[series > 0] = (
        series[series > 0]
        * (
            up_efficiency[series > 0]
            if isinstance(up_efficiency, pd.Series)
            else up_efficiency
        )
        * (resolution / timedelta(hours=1))
    )
    stock_change.loc[series <= 0] = (
        series[series <= 0]
        / (
            down_efficiency[series <= 0]
            if isinstance(down_efficiency, pd.Series)
            else down_efficiency
        )
        * (resolution / timedelta(hours=1))
    )

    stocks = apply_stock_changes_and_losses(
        initial_stock, stock_change.tolist(), storage_efficiency.tolist()
    )
    stocks = pd.concat(
        [
            pd.Series(initial_stock, index=pd.date_range(series.index[0], periods=1)),
            pd.Series(stocks[1:], index=series.index).shift(1, freq=resolution),
        ]
    )
    if decimal_precision is not None:
        stocks = stocks.round(decimal_precision)
    return stocks
