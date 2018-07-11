from typing import List, Dict, Tuple, Union, Callable
from datetime import datetime, timedelta

from flask import session
import pandas as pd
from sqlalchemy.orm.query import Query

from bvp.utils import time_utils
from bvp.data.config import db


def collect_time_series_data(
    generic_asset_names: List[str],
    make_query: Callable[
        [str, Tuple[datetime, datetime], Tuple[timedelta, timedelta]], Query
    ],
    query_window: Tuple[datetime, datetime] = (None, None),
    horizon_window: Tuple[timedelta, timedelta] = (None, None),
    resolution: str = None,
    sum_multiple: bool = True,
    create_if_empty: bool = False,
    zero_if_nan: bool = False,
) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """Get time series data from one or more generic assets and rescale and re-package it to order.

    We can (lazily) look up by pickle, or load from the database.
    In the latter case, we are relying on time series data (power measurements and prices at this point) to
    have the same relevant column names (datetime, value).
    We require a list of assets or market names to find the generic asset.
    If the time range parameters are None, they will be gotten from the session.
    Response is a 2D data frame with the usual columns (y, yhat, ...).
    If data from multiple assets is retrieved, the results are being summed.
    Or, if sum_multiple is False, the response will be a dictionary with asset names
    as keys and data frames as values.
    The response might be an empty data frame if no data exists for these assets
    in this time range.
    If an empty data frame would be returned, but create_if_empty is True, then
    a new DataFrame with the correct datetime index but zeroes as content is returned.
    """
    data_as_dict: Dict[str, pd.DataFrame] = {}
    data_as_df: pd.DataFrame() = pd.DataFrame()

    query_window, resolution = ensure_timing_vars_are_set(query_window, resolution)

    for generic_asset_name in generic_asset_names:

        values = query_time_series_data(
            generic_asset_name,
            make_query,
            query_window,
            horizon_window,
            resolution,
            create_if_empty,
            zero_if_nan,
        )

        # Here we only build one data frame, summed up if necessary.
        if sum_multiple is True:
            if data_as_df.empty:
                data_as_df = values
            elif not values.empty:
                data_as_df = data_as_df.add(values)
        else:  # Here we build a dict with data frames.
            if len(data_as_dict.keys()) == 0:
                data_as_dict = {generic_asset_name: values}
            else:
                data_as_dict[generic_asset_name] = values

    if sum_multiple is True:
        return data_as_df
    else:
        return data_as_dict


def query_time_series_data(
    generic_asset_name: str,
    make_query: Callable[
        [str, Tuple[datetime, datetime], Tuple[timedelta, timedelta]], Query
    ],
    query_window: Tuple[datetime, datetime] = (None, None),
    horizon_window: Tuple[timedelta, timedelta] = (None, None),
    resolution: str = None,
    create_if_empty: bool = False,
    zero_if_nan: bool = False,
) -> pd.DataFrame:
    """
    Run a query for time series data on the database.
    Here, we need to know that postgres only stores naive datetimes and we keep them as UTC.
    Therefore, we localize the result.
    Then, we resample the result, to fit the given resolution.
    If wanted, we can create a DataFrame with zeroes if no results were found in the database.
    Returns a DataFrame with a "y" column.
    """
    query = make_query(generic_asset_name, query_window, horizon_window)
    values_orig = pd.read_sql(
        query.statement, db.session.bind, parse_dates=["datetime"]
    )
    values_orig.rename(index=str, columns={"value": "y"}, inplace=True)
    values_orig.set_index("datetime", drop=True, inplace=True)
    if values_orig.index.tzinfo is None:
        values_orig.index = values_orig.index.tz_localize(time_utils.get_timezone())
    else:
        values_orig.index = values_orig.index.tz_convert(time_utils.get_timezone())

    # re-sample data to the resolution we need to serve
    values = values_orig.resample(resolution).mean()

    # make zero-based result if no values were found
    if values.empty and create_if_empty:
        start = query_window[0]
        end = query_window[1]
        time_steps = pd.date_range(
            start, end, freq=resolution, tz=time_utils.get_timezone()
        )
        values = pd.DataFrame(index=time_steps, columns=["y"])
    if zero_if_nan:
        values.fillna(0.)
    return values


def ensure_timing_vars_are_set(
    time_window: Tuple[datetime, datetime], resolution: str
) -> Tuple[Tuple[datetime, datetime], str]:
    start = time_window[0]
    end = time_window[1]
    if (
        start is None
        or end is None
        or (resolution is None and "resolution" not in session)
    ):
        time_utils.set_time_range_for_session()
        start = session["start_time"]
        end = session["end_time"]
        resolution = session["resolution"]

    return (start, end), resolution


def extract_forecasts(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract forecast columns (given the chosen horizon) and give them the standard naming.
    Returns an empty DataFrame if the expected forecast columns don't exist.
    """
    forecast_columns = [
        "yhat",
        "yhat_upper",
        "yhat_lower",
    ]  # this is what the plotter expects
    horizon = session["forecast_horizon"]
    forecast_renaming = {
        "yhat_%s" % horizon: "yhat",
        "yhat_%s_upper" % horizon: "yhat_upper",
        "yhat_%s_lower" % horizon: "yhat_lower",
    }
    if "yhat_%s" % horizon not in df.columns:
        return pd.DataFrame()
    return df.rename(forecast_renaming, axis="columns")[forecast_columns]
