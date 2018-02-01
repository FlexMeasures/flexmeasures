from datetime import timedelta
from typing import List, Tuple

import pandas as pd
import models
from fbprophet import Prophet


# Maybe we want to make a model separately
# def make_model_for(data: pd.Series):
#    return data


def make_rolling_forecast(data: pd.Series,
                          asset_type: models.AssetType,
                          resolution: str) -> Tuple[pd.DataFrame, List[str]]:
    """Return a df with three series per forecasting horizon,
    forecast from the historic data in a rolling fashion: yhat_{horizon}, yhat_{horizon}_upper and yhat_{horizon}_lower
    (naming follows convention, e.g. from Prophet).
    It will be indexed the same way as the given data series.
    """

    # Rename the datetime and data column for use in fbprophet
    df = pd.DataFrame({'ds': data.index, 'y': data.values})


    if resolution in ("15T", "1h"):
        return _make_rough_rolling_forecast(df, asset_type, resolution)
    elif resolution in ("1d", "1w"):  # for now, keep doing the cheap weay for these
        return _make_in_sample_forecast(df, asset_type, resolution)


def _make_in_sample_forecast(data: pd.DataFrame, asset_type: models.AssetType, resolution: str)\
                             -> Tuple[pd.DataFrame, List[str]]:
    """
    Run cheap inner-sample forecasts, return yhat[_horizon][_upper,_lower] data frame.
    Forecasts are made for the resolution, we fake the horizon in the name for 1d to be 48h.
    Return the forecasts and a list of horizons.
    """
    # Precondition the model to look for certain trends and seasonalities, and fit it
    model = Prophet(interval_width=models.confidence_interval_width, **asset_type.preconditions)

    model.fit(data)

    # Select a time window for the forecast
    start_ = model.history_dates.min()
    end_ = model.history_dates.max()
    dates = pd.date_range(start=start_, end=end_, freq=resolution)

    window = pd.DataFrame({'ds': dates})

    forecasts = model.predict(window)

    horizon = resolution
    if resolution == "1d":
        horizon = "48h"
    columns = ["yhat_%s" % horizon, "yhat_%s_upper" % horizon, "yhat_%s_lower" % horizon]
    confidence_df = pd.DataFrame(index=data.index, columns=columns)
    for col in columns:
        confidence_df[col] = forecasts[col.replace("_%s" % horizon, "")].values

    return confidence_df, [horizon,]


def _make_rough_rolling_forecast(data: pd.DataFrame, asset_type: models.AssetType, resolution: str)\
                                 -> Tuple[pd.DataFrame, List[str]]:
    """
    Run a rolling forecast, with a trick to save on the time this takes.

    We build a model every 6 hours. We forecast 52 hours from there. From this forecast,
    we pick two windows, around 6h and 48h, and apply these forecasts, *as if they were made
    exactly 6h/48h before*, where in reality there are from *roughly* 6h/48h before.
    The results will probably not differ a lot, but our computation time is cut by a factor of six to twenty-four.
    Return the forecasts and a list of horizons.

    TODO: make work for resolutions 1d and 1w as well.
    """
    initial_training = timedelta(days=7)
    modeling_times = pd.date_range(start='2015-01-01 00:00', end="2015-01-11 23:45", freq="6h")
    forecast_times = pd.date_range(start='2015-01-01 00:00', end="2015-01-11 23:45", freq=resolution)

    periods_forward = 0
    sliding_window = []
    if resolution == "1h":
        periods_forward = 52
        sliding_window = [timedelta(hours=step) for step in range(-3, 4)]
    elif resolution == "15T":
        periods_forward = 52 * 4
        sliding_window = [timedelta(minutes=15 * step) for step in range(-12, 13)]

    forecast_6h_ago = pd.DataFrame(columns=["ds", "yhat", "yhat_upper", "yhat_lower"])
    forecast_6h_ago["ds"] = forecast_times
    forecast_48h_ago = pd.DataFrame(columns=["ds", "yhat", "yhat_upper", "yhat_lower"])
    forecast_48h_ago["ds"] = forecast_times

    yhats = ["yhat", "yhat_upper", "yhat_lower"]

    for dt in modeling_times:
        if dt < modeling_times[0] + initial_training:
            continue  # wait for initial training
        if dt.hour == 0:
            print(dt)
        model = Prophet(interval_width=models.confidence_interval_width, **asset_type.preconditions)
        model.fit(data[data["ds"] <= dt])
        future = model.make_future_dataframe(freq=resolution, periods=periods_forward)
        forecast_at_dt = model.predict(future)
        for timestep in sliding_window:
            forecast_6h_ago.loc[forecast_6h_ago["ds"] == dt + timedelta(hours=6) + timestep, yhats] = \
                forecast_at_dt.loc[forecast_at_dt["ds"] == dt + timedelta(hours=6) + timestep, yhats].values
            forecast_48h_ago.loc[forecast_48h_ago["ds"] == dt + timedelta(hours=48) + timestep, yhats] = \
                forecast_at_dt.loc[forecast_at_dt["ds"] == dt + timedelta(hours=48) + timestep, yhats].values

    # We fill NaN values with zeroes for now.
    # There might be a better way for our app to handle times without forecasts data.
    forecast_6h_ago.fillna(0, inplace=True)
    forecast_48h_ago.fillna(0, inplace=True)

    # Put only the confidence intervals for the forecast in a separate df
    columns = ["yhat_6h", "yhat_6h_upper", "yhat_6h_lower",
               "yhat_48h", "yhat_48h_upper", "yhat_48h_lower"]
    forecast_df = pd.DataFrame(index=data.index, columns=columns)
    for col in columns:
        if "6h" in col:
            forecast_df[col] = forecast_6h_ago[col.replace("_6h", "")].values
        else:
            forecast_df[col] = forecast_48h_ago[col.replace("_48h", "")].values

    return forecast_df, ["6h", "48"]
