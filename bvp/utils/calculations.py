""" Calculations """

import numpy as np


def mean_absolute_error(y_true, y_forecast):
    y_true, y_forecast = np.array(y_true), np.array(y_forecast)
    return np.mean(np.abs((y_true - y_forecast)))


def mean_absolute_percentage_error(y_true, y_forecast):
    if 0 in y_true:
        return np.nan
    else:
        y_true, y_forecast = np.array(y_true), np.array(y_forecast)
        return np.mean(np.abs((y_true - y_forecast) / y_true)) * 100


def weighted_absolute_percentage_error(y_true, y_forecast):
    if sum(y_true) == 0:
        return np.nan
    else:
        y_true, y_forecast = np.array(y_true), np.array(y_forecast)
        return np.sum(np.abs((y_true - y_forecast))) / np.sum(y_true) * 100
