from typing import List, Dict, Tuple, Union, Callable
from datetime import datetime, timedelta

from flask import current_app, session
import pandas as pd
from sqlalchemy.orm.query import Query
import numpy as np
import inflect
from inflection import humanize

from bvp.utils import time_utils
from bvp.data.config import db


p = inflect.engine()


def collect_time_series_data(
    generic_asset_names: Union[str, List[str]],
    make_query: Callable[
        [str, Tuple[datetime, datetime], Tuple[timedelta, timedelta]], Query
    ],
    query_window: Tuple[datetime, datetime] = (None, None),
    horizon_window: Tuple[timedelta, timedelta] = (None, None),
    rolling: bool = True,
    preferred_source_ids: {
        Union[int, List[int]]
    } = None,  # None is interpreted as all sources
    fallback_source_ids: Union[
        int, List[int]
    ] = -1,  # An id = -1 is interpreted as no sources
    resolution: str = None,
    sum_multiple: bool = True,
    create_if_empty: bool = False,
    zero_if_nan: bool = False,
    as_beliefs: bool = False,
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
    a new DataFrame with the correct datetime index but nan or zero values as content is returned,
    depending on the zero_if_nan parameter.
    """
    if isinstance(generic_asset_names, str):
        generic_asset_names = [generic_asset_names]
    elif len(generic_asset_names) > 1 and sum_multiple and as_beliefs:
        current_app.logger.error(
            "Summing over horizons and data source labels is not implemented."
        )

    data_as_dict: Dict[str, pd.DataFrame] = {}
    data_as_df: pd.DataFrame() = pd.DataFrame()

    query_window, resolution = ensure_timing_vars_are_set(query_window, resolution)

    for generic_asset_name in generic_asset_names:

        values = query_time_series_data(
            generic_asset_name,
            make_query,
            query_window,
            horizon_window,
            rolling,
            preferred_source_ids,
            resolution,
            create_if_empty,
            zero_if_nan,
            as_beliefs=as_beliefs,
        )

        # Cases explaining the following if statement for when to do a fallback query:
        # 1)    p = None, f = -1          query all sources using id = None
        # 2)    p = None, f = None        query all sources using id = None
        # 3)    p = None, f = 1           query all sources using id = None
        # 4)    p = 1, f = 1              query one source using id = 1 (id = 1 already queried)
        # 5)    p = 1, f = None           query one source using id = 1,
        #                                 if values == None then query all source using id = None
        # 6)    p = 1, f = 2              query one source using id = 1,
        #                                 if values == None then query one source using id = 2
        # 7)    p = [1, 2], f = [2, 3]    query two sources with id = 1 or id = 2,
        #                                 if values == None then query one source with id = 3 (id = 2 already queried)
        # So the general rule is:
        #   - if the preferred sources don't have values
        #   - and if we didn't query all sources already (catches case 1, 2 and 3)
        #   - and if there are unique fallback sources stated (catches case 4 and part of 7)

        # As a fallback, we'll only query sources that were not queried already (except if the fallback is to query all)
        unique_fallback_source_ids = drop_non_unique_elements(
            preferred_source_ids, fallback_source_ids
        )  # now a list

        if (
            values.empty
            and preferred_source_ids
            and -1 not in unique_fallback_source_ids
        ):
            values = query_time_series_data(
                generic_asset_name,
                make_query,
                query_window,
                horizon_window,
                rolling,
                unique_fallback_source_ids,
                resolution,
                create_if_empty,
                zero_if_nan,
                as_beliefs=as_beliefs,
            )

        # Here we only build one data frame, summed up if necessary.
        if sum_multiple is True:
            if data_as_df.empty:
                data_as_df = values
            elif not values.empty:
                data_as_df.y = data_as_df.y.add(values.y, fill_value=0)
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
        [
            str,
            Tuple[datetime, datetime],
            Tuple[timedelta, timedelta],
            bool,
            Union[int, List[int]],
        ],
        Query,
    ],
    query_window: Tuple[datetime, datetime] = (None, None),
    horizon_window: Tuple[timedelta, timedelta] = (None, None),
    rolling: bool = True,
    source_ids: Union[int, List[int]] = None,
    resolution: str = None,
    create_if_empty: bool = False,
    zero_if_nan: bool = False,
    as_beliefs: bool = False,
) -> pd.DataFrame:
    """
    Run a query for time series data on the database.
    Here, we need to know that postgres only stores naive datetimes and we keep them as UTC.
    Therefore, we localize the result.
    Then, we resample the result, to fit the given resolution.
    If wanted, we can create a DataFrame with zeroes if no results were found in the database.
    Returns a DataFrame with a "y" column if as_beliefs is False, otherwise returns a DataFrame with "y", "horizon"
    and "label" columns.
    """
    query = make_query(
        generic_asset_name, query_window, horizon_window, rolling, source_ids
    )
    values_orig = pd.read_sql(query.statement, db.session.bind)
    values_orig["datetime"] = pd.to_datetime(values_orig["datetime"], utc=True)

    # Keep the most recent observation
    values_orig = (
        values_orig.sort_values(by=["horizon"], ascending=True)
        .drop_duplicates(subset=["datetime"], keep="first")
        .sort_values(by=["datetime"])
    )

    # Drop the horizon and label if the requested values do not have to be represented as beliefs
    if as_beliefs is False:
        values_orig = values_orig.loc[:, ["datetime", "value"]]

    # Index according to time and rename value column
    values_orig.rename(index=str, columns={"value": "y"}, inplace=True)
    values_orig.set_index("datetime", drop=True, inplace=True)

    # Convert to the timezone for the user
    if values_orig.index.tzinfo is None:
        values_orig.index = values_orig.index.tz_localize(time_utils.get_timezone())
    else:
        values_orig.index = values_orig.index.tz_convert(time_utils.get_timezone())

    # Parse the data resolution and make sure the full query window is represented
    # TODO: get resolution for the asset as stored in the database
    if not values_orig.empty:
        new_index = pd.DatetimeIndex(
            start=query_window[0], end=query_window[1], freq="15T", closed="left"
        )
        new_index = new_index.tz_convert(time_utils.get_timezone())
        values_orig = values_orig.reindex(new_index)

    # re-sample data to the resolution we need to serve
    if not values_orig.empty:
        if all(k in values_orig for k in ("horizon", "label")):
            values = values_orig.resample(resolution).aggregate(
                {
                    "y": np.nanmean,
                    "horizon": lambda x: horizon_resampler(
                        x
                    ),  # list of unique horizons w.r.t. new time slot
                    "label": lambda x: data_source_resampler(x),
                }
            )
        else:
            values = values_orig.resample(resolution).aggregate({"y": np.nanmean})
    else:
        values = values_orig

    # make nan-based or zero-based result if no values were found
    if values.empty and create_if_empty:
        start = query_window[0]
        end = query_window[1]
        time_steps = pd.date_range(
            start, end, freq=resolution, tz=time_utils.get_timezone(), closed="left"
        )
        if as_beliefs:
            values = pd.DataFrame(index=time_steps, columns=["y", "horizon", "label"])
        else:
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


def drop_non_unique_elements(
    a: Union[int, List[int]], b: Union[int, List[int]]
) -> List[int]:
    """Removes all elements from B that are already in A."""
    a = a if type(a) == list else [a]
    b = b if type(b) == list else [b]
    return list(set(b).difference(a))  # just the unique ones


def data_source_resampler(labels: pd.Series) -> str:
    """Join unique data source labels in a human readable way."""
    unique_labels = labels.unique().tolist()
    unique_labels = [l for l in unique_labels if str(l) not in ["nan", ""]]
    new_label = humanize(p.join(unique_labels))
    return new_label


def horizon_resampler(horizons: pd.Series) -> List[timedelta]:
    """
    Resample horizons to be relative to the new time slot.

    For resampling, it doesn't matter whether horizons are anchored by the start or end of each time slot.
    If you want to change this class to return the actual time of belief, though, you should be mindful of how the
    horizon is anchored. If the horizons are anchored by the end of each time slot, you should add the data resolution
    to get the time of belief (and then subtract it again when calculating the new horizons), because the data is
    indexed by the start of each time slot.
    """

    times_of_belief = horizons.index - horizons.values
    unique_times_of_belief = times_of_belief.unique().tolist()
    unique_horizons_of_belief = [
        horizons.tail(1).index - time for time in unique_times_of_belief
    ]

    return unique_horizons_of_belief
