from typing import List, Dict, Optional, Union, Tuple
from datetime import datetime as datetime_type, timedelta

from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import Query, Session
import timely_beliefs as tb
from marshmallow import Schema, fields

from flexmeasures.data.config import db
from flexmeasures.data import ma
from flexmeasures.data.queries.utils import (
    add_belief_timing_filter,
    add_user_source_filter,
    add_source_type_filter,
    create_beliefs_query,
    exclude_source_type_filter,
)
from flexmeasures.data.services.time_series import collect_time_series_data


class Sensor(db.Model, tb.SensorDBMixin):
    """A sensor measures events. """


class SensorSchema(Schema):
    """
    Base sensor schema.

    Here we include all fields which are implemented by timely_beliefs.SensorDBMixin
    All classes inheriting from timely beliefs sensor don't need to repeat these.
    In a while, this schema can represent our unified Sensor class.

    When subclassing, also subclass from `ma.SQLAlchemySchema` and add your own DB model class, e.g.:

        class Meta:
            model = Asset
    """

    name = ma.auto_field(required=True)
    unit = ma.auto_field(required=True)
    timezone = ma.auto_field()
    event_resolution = fields.TimeDelta(required=True, precision="minutes")


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
        return db.Column(db.DateTime(timezone=True), primary_key=True, index=True)

    """The time delta of measuring or forecasting.
    This should be a duration in ISO8601, e.g. "PT10M", which you can turn into a timedelta with
    isodate.parse_duration, optionally with a minus sign, e.g. "-PT10M".
    Positive durations indicate a forecast into the future, negative ones a backward forecast into the past or simply
    a measurement after the fact.
    """

    @declared_attr
    def horizon(cls):  # noqa: B902
        return db.Column(
            db.Interval(), nullable=False, primary_key=True
        )  # todo: default=timedelta(hours=0)

    """The value."""

    @declared_attr
    def value(cls):  # noqa: B902
        return db.Column(db.Float, nullable=False)

    """The data source."""

    @declared_attr
    def data_source_id(cls):  # noqa: B902
        return db.Column(db.Integer, db.ForeignKey("data_source.id"), primary_key=True)

    @classmethod
    def make_query(
        cls,
        asset_class: db.Model,
        asset_names: Tuple[str],
        query_window: Tuple[Optional[datetime_type], Optional[datetime_type]],
        belief_horizon_window: Tuple[Optional[timedelta], Optional[timedelta]] = (
            None,
            None,
        ),
        belief_time_window: Tuple[Optional[datetime_type], Optional[datetime_type]] = (
            None,
            None,
        ),
        belief_time: Optional[datetime_type] = None,
        user_source_ids: Optional[Union[int, List[int]]] = None,
        source_types: Optional[List[str]] = None,
        exclude_source_types: Optional[List[str]] = None,
        session: Session = None,
    ) -> Query:
        """
        Can be extended with the make_query function in subclasses.
        We identify the assets by their name, which assumes a unique string field can be used.
        The query window consists of two optional datetimes (start and end).
        The horizon window expects first the shorter horizon (e.g. 6H) and then the longer horizon (e.g. 24H).
        The session can be supplied, but if None, the implementation should find a session itself.

        :param user_source_ids: Optional list of user source ids to query only specific user sources
        :param source_types: Optional list of source type names to query only specific source types *
        :param exclude_source_types: Optional list of source type names to exclude specific source types *

        * If user_source_ids is specified, the "user" source type is automatically included (and not excluded).
          Somewhat redundant, but still allowed is to set both source_types and exclude_source_types.


        # todo: add examples
        # todo: switch to using timely_beliefs queries, which are more powerful
        """
        if session is None:
            session = db.session
        start, end = query_window
        query = create_beliefs_query(cls, session, asset_class, asset_names, start, end)
        query = add_belief_timing_filter(
            cls, query, asset_class, belief_horizon_window, belief_time_window
        )
        if user_source_ids:
            query = add_user_source_filter(cls, query, user_source_ids)
        if source_types:
            if user_source_ids and "user" not in source_types:
                source_types.append("user")
            query = add_source_type_filter(cls, query, source_types)
        if exclude_source_types:
            if user_source_ids and "user" in exclude_source_types:
                exclude_source_types.remove("user")
            query = exclude_source_type_filter(cls, query, exclude_source_types)
        return query

    @classmethod
    def collect(
        cls,
        generic_asset_names: Union[str, List[str]],
        query_window: Tuple[Optional[datetime_type], Optional[datetime_type]] = (
            None,
            None,
        ),
        belief_horizon_window: Tuple[Optional[timedelta], Optional[timedelta]] = (
            None,
            None,
        ),
        belief_time_window: Tuple[Optional[datetime_type], Optional[datetime_type]] = (
            None,
            None,
        ),
        user_source_ids: Union[
            int, List[int]
        ] = None,  # None is interpreted as all sources
        source_types: Optional[List[str]] = None,
        exclude_source_types: Optional[List[str]] = None,
        resolution: Union[str, timedelta] = None,
        sum_multiple: bool = True,
    ) -> Union[tb.BeliefsDataFrame, Dict[str, tb.BeliefsDataFrame]]:
        """Basically a convenience wrapper for services.collect_time_series_data,
        where time series data collection is implemented.
        """
        return collect_time_series_data(
            generic_asset_names=generic_asset_names,
            make_query=cls.make_query,
            query_window=query_window,
            belief_horizon_window=belief_horizon_window,
            belief_time_window=belief_time_window,
            user_source_ids=user_source_ids,
            source_types=source_types,
            exclude_source_types=exclude_source_types,
            resolution=resolution,
            sum_multiple=sum_multiple,
        )
