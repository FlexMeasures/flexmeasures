from typing import List, Optional, Tuple, Union
from datetime import datetime, timedelta

from sqlalchemy.orm import Query, Session

from bvp.data.config import db
from bvp.data.models.data_sources import DataSource


def create_beliefs_query(
    cls,
    session: Session,
    asset_class: db.Model,
    asset_name: str,
    start: datetime,
    end: datetime,
) -> Query:
    query = (
        session.query(cls.datetime, cls.value, cls.horizon, DataSource.label)
        .join(DataSource)
        .filter(cls.data_source_id == DataSource.id)
        .join(asset_class)
        .filter(asset_class.name == asset_name)
        .filter((cls.datetime > start - asset_class.resolution) & (cls.datetime < end))
    )
    return query


def assign_source_ids(cls, query: Query, source_ids: Union[int, List[int]]) -> Query:
    if source_ids is not None and not isinstance(source_ids, list):
        source_ids = [source_ids]  # ensure source_ids is a list
    if source_ids:
        # Collect only data from sources that are either a specified user id or a script
        script_sources = DataSource.query.filter(DataSource.type == "script").all()
        user_sources = (
            DataSource.query.filter(DataSource.type == "user")
            .filter(DataSource.id.in_(source_ids))
            .all()
        )
        script_source_ids = [script_source.id for script_source in script_sources]
        user_source_ids = [user_source.id for user_source in user_sources]
        query = query.filter(
            cls.data_source_id.in_(user_source_ids)
            | cls.data_source_id.in_(script_source_ids)
        )
    return query


def assign_horizon_window(
    cls,
    query: Query,
    end: datetime,
    asset_class: db.Model,
    horizon_window: Tuple[Optional[timedelta], Optional[timedelta]],
    rolling: bool,
) -> Query:
    short_horizon, long_horizon = horizon_window
    if (
        short_horizon is not None
        and long_horizon is not None
        and short_horizon == long_horizon
    ):
        if rolling:
            query = query.filter(cls.horizon == short_horizon)
        else:  # Deduct the difference in end times of the timeslot and the query window
            query = query.filter(
                cls.horizon
                == short_horizon - (end - (cls.datetime + asset_class.resolution))
            )
    else:
        if short_horizon is not None:
            if rolling:
                query = query.filter(cls.horizon >= short_horizon)
            else:
                query = query.filter(
                    cls.horizon
                    >= short_horizon - (end - (cls.datetime + asset_class.resolution))
                )
        if long_horizon is not None:
            if rolling:
                query = query.filter(cls.horizon <= long_horizon)
            else:
                query = query.filter(
                    cls.horizon
                    <= long_horizon - (end - (cls.datetime + asset_class.resolution))
                )
    return query
