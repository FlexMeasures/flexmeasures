""" Calculations """

import numpy as np


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
        return np.mean(np.abs((y_true - y_forecast) / y_true)) * 100


def weighted_absolute_percentage_error(y_true: np.ndarray, y_forecast: np.ndarray):
    y_true, y_forecast = drop_nan_rows(y_true, y_forecast)
    if y_true.size == 0 or y_forecast.size == 0 or sum(y_true) == 0:
        return np.nan
    else:
        return np.sum(np.abs((y_true - y_forecast))) / np.sum(y_true) * 100


def drop_nan_rows(a, b):
    d = np.array(list(zip(a, b)))
    d = d[~np.any(np.isnan(d), axis=1)]
    return d[:, 0], d[:, 1]
