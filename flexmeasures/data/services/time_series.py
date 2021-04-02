from typing import List, Dict, Optional, Tuple, Union, Callable
from datetime import datetime, timedelta

import inflect
from flask import current_app
import pandas as pd
from sqlalchemy.orm.query import Query
import timely_beliefs as tb
import isodate

from flexmeasures.data.queries.utils import simplify_index
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.utils import time_utils


p = inflect.engine()

# Signature of a callable that build queries
QueryCallType = Callable[
    [
        Tuple[str],
        Tuple[datetime, datetime],
        Tuple[Optional[timedelta], Optional[timedelta]],
        Tuple[Optional[datetime], Optional[datetime]],
        Optional[datetime],
        Optional[Union[int, List[int]]],
        Optional[List[str]],
        Optional[List[str]],
    ],
    Query,
]


def collect_time_series_data(
    generic_asset_names: Union[str, List[str]],
    make_query: QueryCallType,
    query_window: Tuple[Optional[datetime], Optional[datetime]] = (None, None),
    belief_horizon_window: Tuple[Optional[timedelta], Optional[timedelta]] = (
        None,
        None,
    ),
    belief_time_window: Tuple[Optional[datetime], Optional[datetime]] = (None, None),
    belief_time: Optional[datetime] = None,
    user_source_ids: Union[int, List[int]] = None,  # None is interpreted as all sources
    source_types: Optional[List[str]] = None,
    exclude_source_types: Optional[List[str]] = None,
    resolution: Union[str, timedelta] = None,
    sum_multiple: bool = True,
) -> Union[tb.BeliefsDataFrame, Dict[str, tb.BeliefsDataFrame]]:
    """Get time series data from one or more generic assets and rescale and re-package it to order.

    We can (lazily) look up by pickle, or load from the database.
    In the latter case, we are relying on time series data (power measurements and prices at this point) to
    have the same relevant column names (datetime, value).
    We require a list of assets or market names to find the generic asset.
    If the time range parameters are None, they will be gotten from the session.
    Response is a 2D BeliefsDataFrame with the column event_value.
    If data from multiple assets is retrieved, the results are being summed.
    Or, if sum_multiple is False, the response will be a dictionary with asset names
    as keys, each holding a BeliefsDataFrame as its value.
    The response might be an empty data frame if no data exists for these assets
    in this time range.
    """

    # convert to tuple to support caching the query
    if isinstance(generic_asset_names, str):
        generic_asset_names = (generic_asset_names,)
    elif isinstance(generic_asset_names, list):
        generic_asset_names = tuple(generic_asset_names)

    bdf_dict = query_time_series_data(
        generic_asset_names,
        make_query,
        query_window,
        belief_horizon_window,
        belief_time_window,
        belief_time,
        user_source_ids,
        source_types,
        exclude_source_types,
        resolution,
    )

    if sum_multiple is True:
        return aggregate_values(bdf_dict)
    else:
        return bdf_dict


def query_time_series_data(
    generic_asset_names: Tuple[str],
    make_query: QueryCallType,
    query_window: Tuple[Optional[datetime], Optional[datetime]] = (None, None),
    belief_horizon_window: Tuple[Optional[timedelta], Optional[timedelta]] = (
        None,
        None,
    ),
    belief_time_window: Tuple[Optional[datetime], Optional[datetime]] = (None, None),
    belief_time: Optional[datetime] = None,
    user_source_ids: Optional[Union[int, List[int]]] = None,
    source_types: Optional[List[str]] = None,
    exclude_source_types: Optional[List[str]] = None,
    resolution: Union[str, timedelta] = None,
) -> Dict[str, tb.BeliefsDataFrame]:
    """
    Run a query for time series data on the database for a tuple of assets.
    Here, we need to know that postgres only stores naive datetimes and we keep them as UTC.
    Therefore, we localize the result.
    Then, we resample the result, to fit the given resolution. *
    Returns a dictionary of asset names (as keys) and BeliefsDataFrames (as values),
    with each BeliefsDataFrame having an "event_value" column.

    * Note that we convert string resolutions to datetime.timedelta objects.
      Pandas can resample with those, but still has some quirky behaviour with DST:
      see https://github.com/pandas-dev/pandas/issues/35219
    """

    # On demo, we query older data as if it's the current year's data (we convert back below)
    if current_app.config.get("FLEXMEASURES_MODE", "") == "demo":
        query_window = convert_query_window_for_demo(query_window)

    query = make_query(
        asset_names=generic_asset_names,
        query_window=query_window,
        belief_horizon_window=belief_horizon_window,
        belief_time_window=belief_time_window,
        belief_time=belief_time,
        user_source_ids=user_source_ids,
        source_types=source_types,
        exclude_source_types=exclude_source_types,
    )

    df_all_assets = pd.DataFrame(
        query.all(), columns=[col["name"] for col in query.column_descriptions]
    )
    bdf_dict: Dict[str, tb.BeliefsDataFrame] = {}
    for generic_asset_name in generic_asset_names:

        # Select data for the given asset
        df = df_all_assets[df_all_assets["name"] == generic_asset_name].loc[
            :, df_all_assets.columns != "name"
        ]

        # todo: Keep the preferred data source (first look at source_type, then user_source_id if needed)
        # if user_source_ids:
        #     values_orig["source"] = values_orig["source"].astype("category")
        #     values_orig["source"].cat.set_categories(user_source_ids, inplace=True)
        #     values_orig = (
        #         values_orig.sort_values(by=["source"], ascending=True)
        #         .drop_duplicates(subset=["source"], keep="first")
        #         .sort_values(by=["datetime"])
        #     )

        # Keep the most recent observation
        # todo: this block also resolves multi-sourced data by selecting the "first" (unsorted) source; we should have a consistent policy for this case
        df = (
            df.sort_values(by=["horizon"], ascending=True)
            .drop_duplicates(subset=["datetime"], keep="first")
            .sort_values(by=["datetime"])
        )

        # Index according to time and rename columns
        # todo: this operation can be simplified after moving our time series data structures to timely-beliefs
        df.rename(
            index=str,
            columns={
                "value": "event_value",
                "datetime": "event_start",
                "DataSource": "source",
                "horizon": "belief_horizon",
            },
            inplace=True,
        )
        df.set_index("event_start", drop=True, inplace=True)

        # Convert to the FLEXMEASURES timezone
        if not df.empty:
            df.index = df.index.tz_convert(time_utils.get_timezone())

        # On demo, we query older data as if it's the current year's data (we converted above)
        if current_app.config.get("FLEXMEASURES_MODE", "") == "demo":
            df.index = df.index.map(lambda t: t.replace(year=datetime.now().year))

        sensor = find_sensor_by_name(name=generic_asset_name)
        bdf = tb.BeliefsDataFrame(df.reset_index(), sensor=sensor)

        # re-sample data to the resolution we need to serve
        if resolution is None:
            resolution = sensor.event_resolution
        elif isinstance(resolution, str):
            try:
                # todo: allow pandas freqstr as resolution when timely-beliefs supports DateOffsets,
                #       https://github.com/SeitaBV/timely-beliefs/issues/13
                resolution = pd.to_timedelta(resolution).to_pytimedelta()
            except ValueError:
                resolution = isodate.parse_duration(resolution)
        bdf = bdf.resample_events(
            event_resolution=resolution, keep_only_most_recent_belief=True
        )
        bdf_dict[generic_asset_name] = bdf

    return bdf_dict


def find_sensor_by_name(name: str):
    """
    Helper function: Find a sensor by name.
    TODO: make obsolete when we switched to one sensor class (and timely-beliefs)
    """
    # importing here to avoid circular imports, deemed okay for temp. solution
    from flexmeasures.data.models.assets import Asset
    from flexmeasures.data.models.weather import WeatherSensor
    from flexmeasures.data.models.markets import Market

    asset = Asset.query.filter(Asset.name == name).one_or_none()
    if asset:
        return asset
    weather_sensor = WeatherSensor.query.filter(
        WeatherSensor.name == name
    ).one_or_none()
    if weather_sensor:
        return weather_sensor
    market = Market.query.filter(Market.name == name).one_or_none()
    if market:
        return market
    raise Exception("Unknown sensor: %s" % name)


def drop_non_unique_ids(
    a: Union[int, List[int]], b: Union[int, List[int]]
) -> List[int]:
    """Removes all elements from B that are already in A."""
    a_l = a if type(a) == list else [a]
    b_l = b if type(b) == list else [b]
    return list(set(b_l).difference(a_l))  # just the unique ones


def convert_query_window_for_demo(
    query_window: Tuple[datetime, datetime]
) -> Tuple[datetime, datetime]:
    demo_year = current_app.config.get("FLEXMEASURES_DEMO_YEAR", None)
    if demo_year is None:
        return query_window
    try:
        start = query_window[0].replace(year=demo_year)
    except ValueError as e:
        # Expand the query_window in case a leap day was selected
        if "day is out of range for month" in str(e):
            start = (query_window[0] - timedelta(days=1)).replace(year=demo_year)
        else:
            start = query_window[0]
    try:
        end = query_window[-1].replace(year=demo_year)
    except ValueError as e:
        # Expand the query_window in case a leap day was selected
        if "day is out of range for month" in str(e):
            end = (query_window[-1] + timedelta(days=1)).replace(year=demo_year)
        else:
            end = query_window[-1]
    return start, end


def aggregate_values(bdf_dict: Dict[str, tb.BeliefsDataFrame]) -> tb.BeliefsDataFrame:

    # todo: test this function rigorously, e.g. with empty bdfs in bdf_dict
    # todo: consider 1 bdf with beliefs from source A, plus 1 bdf with beliefs from source B -> 1 bdf with sources A+B
    # todo: consider 1 bdf with beliefs from sources A and B, plus 1 bdf with beliefs from source C. -> 1 bdf with sources A+B and A+C
    # todo: consider 1 bdf with beliefs from sources A and B, plus 1 bdf with beliefs from source C and D. -> 1 bdf with sources A+B, A+C, B+C and B+D
    # Relevant issue: https://github.com/SeitaBV/timely-beliefs/issues/33
    unique_source_ids: List[int] = []
    for bdf in bdf_dict.values():
        unique_source_ids.extend(bdf.lineage.sources)
        if not bdf.lineage.unique_beliefs_per_event_per_source:
            current_app.logger.warning(
                "Not implemented: only aggregation of deterministic uni-source beliefs (1 per event) is properly supported"
            )
        if bdf.lineage.number_of_sources > 1:
            current_app.logger.warning(
                "Not implemented: aggregating multi-source beliefs about the same sensor."
            )
    if len(set(unique_source_ids)) > 1:
        current_app.logger.warning(
            f"Not implemented: aggregating multi-source beliefs. Source {unique_source_ids[1:]} will be treated as if source {unique_source_ids[0]}"
        )

    data_as_bdf = tb.BeliefsDataFrame()
    for k, v in bdf_dict.items():
        if data_as_bdf.empty:
            data_as_bdf = v.copy()
        elif not v.empty:
            data_as_bdf["event_value"] = data_as_bdf["event_value"].add(
                simplify_index(v.copy())["event_value"],
                fill_value=0,
                level="event_start",
            )  # we only look at the event_start index level and sum up duplicates that level
    return data_as_bdf


def set_bdf_source(bdf: tb.BeliefsDataFrame, source_name: str) -> tb.BeliefsDataFrame:
    """
    Set the source of the BeliefsDataFrame.
    We do this by re-setting the index (as source probably is part of the BeliefsDataFrame multi index),
    setting the source, then restoring the (multi) index.
    """
    index_cols = bdf.index.names
    bdf = bdf.reset_index()
    bdf["source"] = DataSource(source_name)
    return bdf.set_index(index_cols)
