""" Calculations """

import numpy as np


def mean_absolute_error(y_true, y_forecast):
    y_true, y_forecast = drop_nan_rows(y_true, y_forecast)
    return np.mean(np.abs((y_true - y_forecast)))


def mean_absolute_percentage_error(y_true, y_forecast):
    if 0 in y_true:
        return np.nan
    else:
        y_true, y_forecast = drop_nan_rows(y_true, y_forecast)
        return np.mean(np.abs((y_true - y_forecast) / y_true)) * 100


def weighted_absolute_percentage_error(y_true, y_forecast):
    if sum(y_true) == 0:
        return np.nan
    else:
        y_true, y_forecast = drop_nan_rows(y_true, y_forecast)
        return np.sum(np.abs((y_true - y_forecast))) / np.sum(y_true) * 100


def drop_nan_rows(a, b):
    d = np.array(list(zip(a, b)))
    d = d[~np.any(np.isnan(d), axis=1)]
    return d[:, 0], d[:, 1]
