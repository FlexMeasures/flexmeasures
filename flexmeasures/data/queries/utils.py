from __future__ import annotations

from typing import Type
from datetime import datetime, timedelta

from flask_security import current_user
from werkzeug.exceptions import Forbidden
import pandas as pd
import timely_beliefs as tb
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import BinaryExpression, or_
from sqlalchemy.sql.expression import null
from sqlalchemy import select, Select

from flexmeasures.data.config import db
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.utils import flexmeasures_inflection
from flexmeasures.auth.policy import user_has_admin_access
from flexmeasures.cli import is_running as running_as_cli
import flexmeasures.data.models.time_series as ts  # noqa: F401


def create_beliefs_query(
    cls: "Type[ts.TimedValue]",
    session: Session,
    old_sensor_class: db.Model,
    old_sensor_names: tuple[str],
    start: datetime | None,
    end: datetime | None,
) -> Select:
    query = (
        select(old_sensor_class.name, cls.datetime, cls.value, cls.horizon, DataSource)
        .join(DataSource)
        .filter(cls.data_source_id == DataSource.id)
        .join(old_sensor_class)
        .filter(old_sensor_class.name.in_(old_sensor_names))
    )
    if start is not None:
        query = query.filter((cls.datetime > start - old_sensor_class.event_resolution))
    if end is not None:
        query = query.filter((cls.datetime < end))
    return query


def potentially_limit_assets_query_to_account(
    query: Select[tuple[GenericAsset]],
    account_id: int | None = None,
) -> Select[tuple[GenericAsset]]:
    """Filter out all assets that are not in the current user's account.
    For admins and CLI users, no assets are filtered out, unless an account_id is set.

    :param account_id: if set, all assets that are not in the given account will be filtered out (only works for admins and CLI users). For querying public assets in particular, don't use this function.
    """
    if not running_as_cli() and not current_user.is_authenticated:
        raise Forbidden("Unauthenticated user cannot list assets.")
    user_is_admin = running_as_cli() or user_has_admin_access(
        current_user, permission="read" if query.is_select else "update"
    )
    if account_id is None and user_is_admin:
        return query  # allow admins to query assets across all accounts
    if (
        account_id is not None
        and account_id != current_user.account_id
        and not user_is_admin
    ):
        raise Forbidden("Non-admin cannot access assets from other accounts.")
    account_id_to_filter = (
        account_id if account_id is not None else current_user.account_id
    )
    return query.filter(
        or_(
            GenericAsset.account_id == account_id_to_filter,
            GenericAsset.account_id == null(),
        )
    )


def get_source_criteria(
    cls: "Type[ts.TimedValue] | Type[ts.TimedBelief]",
    user_source_ids: int | list[int],
    source_types: list[str],
    exclude_source_types: list[str],
) -> list[BinaryExpression]:
    source_criteria: list[BinaryExpression] = []
    if user_source_ids is not None:
        source_criteria.append(user_source_criterion(cls, user_source_ids))
    if source_types is not None:
        if user_source_ids and "user" not in source_types:
            source_types.append("user")
        source_criteria.append(source_type_criterion(source_types))
    if exclude_source_types is not None:
        if user_source_ids and "user" in exclude_source_types:
            exclude_source_types.remove("user")
        source_criteria.append(source_type_exclusion_criterion(exclude_source_types))
    return source_criteria


def user_source_criterion(
    cls: "Type[ts.TimedValue] | Type[ts.TimedBelief]",
    user_source_ids: int | list[int],
) -> BinaryExpression:
    """Criterion to search only through user data from the specified user sources.

    We distinguish user sources (sources with source.type == "user") from other sources (source.type != "user").
    Data with a user source originates from a registered user. Data with e.g. a script source originates from a script.

    This criterion doesn't affect the query over non-user type sources.
    It does so by ignoring user sources that are not in the given list of source_ids.
    """
    if user_source_ids is not None and not isinstance(user_source_ids, list):
        user_source_ids = [user_source_ids]  # ensure user_source_ids is a list
    ignorable_user_sources = db.session.scalars(
        select(DataSource)
        .filter(DataSource.type == "user")
        .filter(DataSource.id.not_in(user_source_ids))
    ).all()
    ignorable_user_source_ids = [
        user_source.id for user_source in ignorable_user_sources
    ]

    # todo: [legacy] deprecate this if-statement, which is used to support the TimedValue class
    if hasattr(cls, "data_source_id"):
        return cls.data_source_id.not_in(ignorable_user_source_ids)
    return cls.source_id.not_in(ignorable_user_source_ids)


def source_type_criterion(source_types: list[str]) -> BinaryExpression:
    """Criterion to collect only data from sources that are of the given type."""
    return DataSource.type.in_(source_types)


def source_type_exclusion_criterion(source_types: list[str]) -> BinaryExpression:
    """Criterion to exclude sources that are of the given type."""
    return DataSource.type.not_in(source_types)


def get_belief_timing_criteria(
    cls: "Type[ts.TimedValue]",
    asset_class: db.Model,
    belief_horizon_window: tuple[timedelta | None, timedelta | None],
    belief_time_window: tuple[datetime | None, datetime | None],
) -> list[BinaryExpression]:
    """Get filter criteria for the desired windows with relevant belief times and belief horizons.

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
    criteria: list[BinaryExpression] = []
    earliest_belief_time, latest_belief_time = belief_time_window
    if (
        earliest_belief_time is not None
        and latest_belief_time is not None
        and earliest_belief_time == latest_belief_time
    ):  # search directly for a unique belief time
        criteria.append(
            cls.datetime + asset_class.event_resolution - cls.horizon
            == earliest_belief_time
        )
    else:
        if earliest_belief_time is not None:
            criteria.append(
                cls.datetime + asset_class.event_resolution - cls.horizon
                >= earliest_belief_time
            )
        if latest_belief_time is not None:
            criteria.append(
                cls.datetime + asset_class.event_resolution - cls.horizon
                <= latest_belief_time
            )
    short_horizon, long_horizon = belief_horizon_window
    if (
        short_horizon is not None
        and long_horizon is not None
        and short_horizon == long_horizon
    ):  # search directly for a unique belief horizon
        criteria.append(cls.horizon == short_horizon)
    else:
        if short_horizon is not None:
            criteria.append(cls.horizon >= short_horizon)
        if long_horizon is not None:
            criteria.append(cls.horizon <= long_horizon)
    return criteria


def simplify_index(
    bdf: tb.BeliefsDataFrame, index_levels_to_columns: list[str] | None = None
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
    result_source: str | None = None,
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
