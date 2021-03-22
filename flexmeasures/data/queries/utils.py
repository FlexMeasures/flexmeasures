from typing import List, Optional, Tuple, Union
from datetime import datetime, timedelta

import pandas as pd
import timely_beliefs as tb

from sqlalchemy.orm import Query, Session
from sqlalchemy.engine.result import RowProxy

from flexmeasures.data.config import db
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.utils import flexmeasures_inflection
import flexmeasures.data.models.time_series as ts  # noqa: F401


def create_beliefs_query(
    cls: "ts.TimedValue",
    session: Session,
    asset_class: db.Model,
    asset_names: Tuple[str],
    start: Optional[datetime],
    end: Optional[datetime],
) -> Query:
    query = (
        session.query(
            asset_class.name, cls.datetime, cls.value, cls.horizon, DataSource
        )
        .join(DataSource)
        .filter(cls.data_source_id == DataSource.id)
        .join(asset_class)
        .filter(asset_class.name.in_(asset_names))
    )
    if start is not None:
        query = query.filter((cls.datetime > start - asset_class.event_resolution))
    if end is not None:
        query = query.filter((cls.datetime < end))
    return query


def add_user_source_filter(
    cls: "ts.TimedValue", query: Query, user_source_ids: Union[int, List[int]]
) -> Query:
    """Add filter to the query to search only through user data from the specified user sources.

    We distinguish user sources (sources with source.type == "user") from other sources (source.type != "user").
    Data with a user source originates from a registered user. Data with e.g. a script source originates from a script.

    This filter doesn't affect the query over non-user type sources.
    It does so by ignoring user sources that are not in the given list of source_ids.
    """
    if user_source_ids is not None and not isinstance(user_source_ids, list):
        user_source_ids = [user_source_ids]  # ensure user_source_ids is a list
    if user_source_ids:
        ignorable_user_sources = (
            DataSource.query.filter(DataSource.type == "user")
            .filter(DataSource.id.notin_(user_source_ids))
            .all()
        )
        ignorable_user_source_ids = [
            user_source.id for user_source in ignorable_user_sources
        ]
        query = query.filter(cls.data_source_id.notin_(ignorable_user_source_ids))
    return query


def add_source_type_filter(
    cls: "ts.TimedValue", query: Query, source_types: List[str]
) -> Query:
    """Add filter to the query to collect only data from sources that are of the given type."""
    return query.filter(DataSource.type.in_(source_types)) if source_types else query


def exclude_source_type_filter(
    cls: "ts.TimedValue", query: Query, source_types: List[str]
) -> Query:
    """Add filter to the query to exclude sources that are of the given type."""
    return query.filter(DataSource.type.notin_(source_types)) if source_types else query


def add_belief_timing_filter(
    cls: "ts.TimedValue",
    query: Query,
    asset_class: db.Model,
    belief_horizon_window: Tuple[Optional[timedelta], Optional[timedelta]],
    belief_time_window: Tuple[Optional[datetime], Optional[datetime]],
) -> Query:
    """Add filters for the desired windows with relevant belief times and belief horizons.

    # todo: interpret belief horizons with respect to knowledge time rather than event end.
    - a positive horizon denotes a before-the-fact belief (ex-ante w.r.t. knowledge time)
    - a negative horizon denotes an after-the-fact belief (ex-post w.r.t. knowledge time)

    :param belief_horizon_window: short belief horizon and long belief horizon, each an optional timedelta
        Interpretation:
        - a positive short horizon denotes "at least <horizon> before the fact" (min ex-ante)
        - a positive long horizon denotes "at most <horizon> before the fact" (max ex-ante)
        - a negative short horizon denotes "at most <horizon> after the fact" (max ex-post)
        - a negative long horizon denotes "at least <horizon> after the fact" (min ex-post)
    :param belief_time_window: earliest belief time and latest belief time, each an optional datetime

    Examples (assuming the knowledge time of each event coincides with the end of the event):

        # Query beliefs formed between 1 and 7 days before each individual event
        belief_horizon_window = (timedelta(days=1), timedelta(days=7))

        # Query beliefs formed at least 2 hours before each individual event
        belief_horizon_window = (timedelta(hours=2), None)

        # Query beliefs formed at most 2 hours after each individual event
        belief_horizon_window = (-timedelta(hours=2), None)

        # Query beliefs formed at least after each individual event
        belief_horizon_window = (None, timedelta(hours=0))

        # Query beliefs formed from May 2nd to May 13th (left inclusive, right exclusive)
        belief_time_window = (datetime(2020, 5, 2), datetime(2020, 5, 13))

        # Query beliefs formed from May 14th onwards
        belief_time_window = (datetime(2020, 5, 14), None)

        # Query beliefs formed before May 13th
        belief_time_window = (None, datetime(2020, 5, 13))

    """
    earliest_belief_time, latest_belief_time = belief_time_window
    if (
        earliest_belief_time is not None
        and latest_belief_time is not None
        and earliest_belief_time == latest_belief_time
    ):  # search directly for a unique belief time
        query = query.filter(
            cls.datetime + asset_class.event_resolution - cls.horizon
            == earliest_belief_time
        )
    else:
        if earliest_belief_time is not None:
            query = query.filter(
                cls.datetime + asset_class.event_resolution - cls.horizon
                >= earliest_belief_time
            )
        if latest_belief_time is not None:
            query = query.filter(
                cls.datetime + asset_class.event_resolution - cls.horizon
                <= latest_belief_time
            )
    short_horizon, long_horizon = belief_horizon_window
    if (
        short_horizon is not None
        and long_horizon is not None
        and short_horizon == long_horizon
    ):  # search directly for a unique belief horizon
        query = query.filter(cls.horizon == short_horizon)
    else:
        if short_horizon is not None:
            query = query.filter(cls.horizon >= short_horizon)
        if long_horizon is not None:
            query = query.filter(cls.horizon <= long_horizon)
    return query


def parse_sqlalchemy_results(results: List[RowProxy]) -> List[dict]:
    """
    Returns a list of dicts, whose keys are column names. E.g.:

    data = session.execute("Select latitude from asset;").fetchall()
    for row in parse_sqlalchemy_results(data):
        print("------------")
        for key, val in row:
            print f"{key}: {val}"

    """
    parsed_results: List[dict] = []

    if len(results) == 0:
        return parsed_results

    # results from SQLAlchemy are returned as a list of tuples;
    # this procedure converts it into a list of dicts
    for row_number, row in enumerate(results):
        parsed_results.append({})
        for column_number, value in enumerate(row):
            parsed_results[row_number][row.keys()[column_number]] = value

    return parsed_results


def simplify_index(
    bdf: tb.BeliefsDataFrame, index_levels_to_columns: Optional[List[str]] = None
) -> pd.DataFrame:
    """Drops indices other than event_start.
    Optionally, salvage index levels as new columns.

    Because information stored in the index levels is potentially lost*,
    we cannot guarantee a complete description of beliefs in the BeliefsDataFrame.
    Therefore, we type the result as a regular pandas DataFrame.

    * The index levels are dropped (by overwriting the multi-level index with just the “event_start” index level).
      Only for the columns named in index_levels_to_columns, the relevant information is kept around.
    """
    if index_levels_to_columns is not None:
        for col in index_levels_to_columns:
            try:
                bdf[col] = bdf.index.get_level_values(col)
            except KeyError:
                if hasattr(bdf, col):
                    bdf[col] = getattr(bdf, col)
                elif hasattr(bdf, flexmeasures_inflection.pluralize(col)):
                    bdf[col] = getattr(bdf, flexmeasures_inflection.pluralize(col))
                else:
                    raise KeyError(f"Level {col} not found")
    bdf.index = bdf.index.get_level_values("event_start")
    return bdf


def multiply_dataframe_with_deterministic_beliefs(
    df1: pd.DataFrame,
    df2: pd.DataFrame,
    multiplication_factor: float = 1,
    result_source: Optional[str] = None,
) -> pd.DataFrame:
    """
    Create new DataFrame where the event_value columns of df1 and df2 are multiplied.

    If df1 and df2 have belief_horizon columns, the belief_horizon column of the new DataFrame is
    determined as the minimum of the input horizons.
    The source columns of df1 and df2 are not used. A source column for the new DataFrame can be set
    by passing a result_source (string).

    The index of the resulting DataFrame contains the outer join of the indices of df1 and df2.
    Event values are np.nan for rows that are not in both DataFrames.

    :param df1: DataFrame with "event_value" column and optional "belief_horizon" and "source" columns
    :param df2: DataFrame with "event_value" column and optional "belief_horizon" and "source" columns
    :param multiplication_factor: extra scalar to determine the event_value of the resulting DataFrame
    :param result_source: string label for the source of the resulting DataFrame
    :returns: DataFrame with "event_value" column,
              an additional "belief_horizon" column if both df1 and df2 contain this column, and
              an additional "source" column if result_source is set.
    """
    if df1.empty and df2.empty:
        return df1

    df = (df1["event_value"] * df2["event_value"] * multiplication_factor).to_frame(
        name="event_value"
    )
    if "belief_horizon" in df1.columns and "belief_horizon" in df2.columns:
        df["belief_horizon"] = (
            df1["belief_horizon"]
            .rename("belief_horizon1")
            .to_frame()
            .join(df2["belief_horizon"], how="outer")
            .min(axis=1)
            .rename("belief_horizon")
        )  # Add existing belief_horizon information, keeping only the smaller horizon per row
    if result_source is not None:
        df["source"] = result_source  # also for rows with nan event_value
    return df
