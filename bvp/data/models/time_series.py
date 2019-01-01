from typing import List, Dict, Optional, Union, Tuple
from datetime import datetime as datetime_type, timedelta

import pandas as pd
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import Query, Session

from bvp.data.config import db
from bvp.data.queries.utils import assign_horizon_window, create_beliefs_query
from bvp.data.services.time_series import collect_time_series_data


class TimedValue(object):
    """
    A mixin of all tables that store time series data, either forecasts or measurements.
    Represents one row.
    """

    @declared_attr
    def __tablename__(cls):  # noqa: B902
        return cls.__name__.lower()

    """The time at which the value is supposed to (have) happen(ed)."""

    @declared_attr
    def datetime(cls):  # noqa: B902
        return db.Column(db.DateTime(timezone=True), primary_key=True)

    """The time delta of measuring or forecasting.
    This should be a duration in ISO8601, e.g. "PT10M", which you can turn into a timedelta with
    isodate.parse_duration, optionally with a minus sign, e.g. "-PT10M".
    Positive durations indicate a forecast into the future, negative ones a backward forecast into the past or simply
    a measurement after the fact.
    """

    @declared_attr
    def horizon(cls):  # noqa: B902
        return db.Column(db.Interval(), nullable=False, primary_key=True)

    """The value."""

    @declared_attr
    def value(cls):  # noqa: B902
        return db.Column(db.Float, nullable=False)

    """The data source."""

    @declared_attr
    def data_source_id(cls):  # noqa: B902
        return db.Column(db.Integer, db.ForeignKey("data_sources.id"), primary_key=True)

    @classmethod
    def make_query(
        cls,
        asset_class: db.Model,
        asset_name: str,
        query_window: Tuple[datetime_type, datetime_type],
        horizon_window: Tuple[Optional[timedelta], Optional[timedelta]] = (None, None),
        rolling: bool = True,
        session: Session = None,
    ) -> Query:
        """
        Can be extended with the make_query function in subclasses.
        We identify the asset by name, this assumes a unique string field can be used.
        The query window expects start as well as end
        The horizon window expects first the shorter horizon (e.g. 6H) and then the longer horizon (e.g. 24H).
        The session can be supplied, but if None, the implementation should find a session itself.
        """
        if session is None:
            session = db.session
        start, end = query_window
        query = create_beliefs_query(cls, session, asset_class, asset_name, start, end)
        query = assign_horizon_window(
            cls, query, end, asset_class, horizon_window, rolling
        )
        return query

    @classmethod
    def collect(
        cls,
        generic_asset_names: Union[str, List[str]],
        query_window: Tuple[datetime_type, datetime_type] = (None, None),
        horizon_window: Tuple[Union[None, timedelta], Union[None, timedelta]] = (
            None,
            None,
        ),
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
        """Basically a convenience wrapper for services.collect_time_series_data,
        where time series data collection is implemented.
        """
        return collect_time_series_data(
            generic_asset_names=generic_asset_names,
            make_query=cls.make_query,
            query_window=query_window,
            horizon_window=horizon_window,
            rolling=rolling,
            preferred_source_ids=preferred_source_ids,
            fallback_source_ids=fallback_source_ids,
            resolution=resolution,
            sum_multiple=sum_multiple,
            create_if_empty=create_if_empty,
            zero_if_nan=zero_if_nan,
            as_beliefs=as_beliefs,
        )
