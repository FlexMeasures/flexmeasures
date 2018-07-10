from typing import List, Dict, Union

import pandas as pd
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy import Column, DateTime, Float, String, ForeignKey, Integer
from sqlalchemy.orm import Query, Session

from bvp.data.services.time_series import collect_time_series_data


class TimedValue(object):
    """
    A mixin of all tables that store time series data, either forecasts or measurements.
    Represents one row.
    """

    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()

    """The time at which the value is supposed to (have) happen(ed)."""

    @declared_attr
    def datetime(cls):
        return Column(DateTime(timezone=True), primary_key=True)

    """The time delta of measuring or forecasting.
    This should be a duration in ISO8601, e.g. "PT10M", optionally with a minus sign, e.g. "-PT10M".
    Positive durations indicate a forecast into the future, negative ones a backward forecast into the past or simply
    a measurement after the fact.
    We're trying to use little space here, expand later if necessary."""

    @declared_attr
    def horizon(cls):
        return Column(String(6), nullable=False, primary_key=True)

    """The value."""

    @declared_attr
    def value(cls):
        return Column(Float, nullable=False)

    """The data source."""

    @declared_attr
    def data_source(cls):
        return Column(Integer, ForeignKey("data_sources.id"), primary_key=True)

    @classmethod
    def make_query(
        cls,
        generic_asset_name: str,
        query_start: datetime,
        query_end: datetime,
        session: Session = None,
    ) -> Query:
        """
        Should be overwritten with the make_query function in subclasses.
        """
        pass

    @classmethod
    def collect(
        cls,
        generic_asset_names: List[str],
        start: datetime = None,
        end: datetime = None,
        resolution: str = None,
        horizon: datetime = None,
        sum_multiple: bool = True,
        create_if_empty: bool = False,
        zero_if_nan: bool = False,
    ) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
        """Basically a convenience wrapper for services.collect_time_series_data,
        where time series data collection is implemented."""
        return collect_time_series_data(
            generic_asset_names=generic_asset_names,
            make_query=cls.make_query,
            start=start,
            end=end,
            resolution=resolution,
            horizon=horizon,
            sum_multiple=sum_multiple,
            create_if_empty=create_if_empty,
            zero_if_nan=zero_if_nan,
        )
