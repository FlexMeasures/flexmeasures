from typing import List, Dict, Union

import pandas as pd
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy import Column, DateTime, Float, String

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
    This should be a duration in ISO8601, e.g. "-PT10M".
    Positive durations indicate a forecast, negative ones a measurement after the fact.
    We're trying to use little space here, expand later if necessary."""

    @declared_attr
    def horizon(cls):
        return Column(String(6), nullable=False)

    """The value."""

    @declared_attr
    def value(cls):
        return Column(Float, nullable=False)

    @classmethod
    def collect(
        cls,
        sensor_names: List[str],
        start: datetime = None,
        end: datetime = None,
        resolution: str = None,
        sum_multiple=True,
        create_if_empty=False,
    ) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
        """Basically a convenience wrapper for services.collect_time_series_data,
        where time series data collection is implemented."""
        return collect_time_series_data(
            data_sources=sensor_names,
            make_query=cls.make_query,
            start=start,
            end=end,
            resolution=resolution,
            sum_multiple=sum_multiple,
            create_if_empty=create_if_empty,
        )
