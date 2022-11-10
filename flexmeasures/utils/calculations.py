""" Calculations """
from __future__ import annotations

from datetime import timedelta

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


def integrate_time_series(
    series: pd.Series,
    initial_stock: float,
    up_efficiency: float | pd.Series = 1,
    down_efficiency: float | pd.Series = 1,
    decimal_precision: int | None = None,
) -> pd.Series:
    """Integrate time series of length n and closed="left" (representing a flow)
    to a time series of length n+1 and closed="both" (representing a stock),
    given an initial stock (i.e. the constant of integration).
    The unit of time is hours: i.e. the stock unit is flow unit times hours (e.g. a flow in kW becomes a stock in kWh).
    Optionally, set a decimal precision to round off the results (useful for tests failing over machine precision).

    >>> s = pd.Series([1, 2, 3, 4], index=pd.date_range(datetime(2001, 1, 1, 5), datetime(2001, 1, 1, 6), freq=timedelta(minutes=15), closed="left"))
    >>> integrate_time_series(s, 10)
        2001-01-01 05:00:00    10.00
        2001-01-01 05:15:00    10.25
        2001-01-01 05:30:00    10.75
        2001-01-01 05:45:00    11.50
        2001-01-01 06:00:00    12.50
        Freq: D, dtype: float64

    >>> s = pd.Series([1, 2, 3, 4], index=pd.date_range(datetime(2001, 1, 1, 5), datetime(2001, 1, 1, 7), freq=timedelta(minutes=30), closed="left"))
    >>> integrate_time_series(s, 10)
        2001-01-01 05:00:00    10.0
        2001-01-01 05:30:00    10.5
        2001-01-01 06:00:00    11.5
        2001-01-01 06:30:00    13.0
        2001-01-01 07:00:00    15.0
        dtype: float64
    """
    resolution = pd.to_timedelta(series.index.freq)
    stock_change = pd.Series(data=np.NaN, index=series.index)
    stock_change.loc[series > 0] = series[series > 0] * (
        up_efficiency[series > 0]
        if isinstance(up_efficiency, pd.Series)
        else up_efficiency
    )
    stock_change.loc[series <= 0] = series[series <= 0] / (
        down_efficiency[series <= 0]
        if isinstance(down_efficiency, pd.Series)
        else down_efficiency
    )
    int_s = pd.concat(
        [
            pd.Series(initial_stock, index=pd.date_range(series.index[0], periods=1)),
            stock_change.shift(1, freq=resolution).cumsum()
            * (resolution / timedelta(hours=1))
            + initial_stock,
        ]
    )
    if decimal_precision is not None:
        int_s = int_s.round(decimal_precision)
    return int_s
