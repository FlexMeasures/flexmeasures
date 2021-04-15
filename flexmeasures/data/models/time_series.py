from typing import List, Dict, Optional, Union, Tuple
from datetime import datetime as datetime_type, timedelta
import json

from altair.utils.html import spec_to_html
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import Query, Session
import timely_beliefs as tb
import timely_beliefs.utils as tb_utils
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
from flexmeasures.ui.charts import belief_charts_mapping
from flexmeasures.utils.time_utils import server_now
from flexmeasures.utils.flexmeasures_inflection import capitalize


class Sensor(db.Model, tb.SensorDBMixin):
    """A sensor measures events. """

    def __init__(self, name: str, **kwargs):
        tb.SensorDBMixin.__init__(self, name, **kwargs)
        tb_utils.remove_class_init_kwargs(tb.SensorDBMixin, kwargs)
        db.Model.__init__(self, **kwargs)

    def search_beliefs(
        self,
        event_starts_after: Optional[datetime_type] = None,
        event_ends_before: Optional[datetime_type] = None,
        beliefs_after: Optional[datetime_type] = None,
        beliefs_before: Optional[datetime_type] = None,
        source: Optional[Union[int, List[int], str, List[str]]] = None,
    ):
        """Search all beliefs about events for this sensor.

        :param event_starts_after: only return beliefs about events that start after this datetime (inclusive)
        :param event_ends_before: only return beliefs about events that end before this datetime (inclusive)
        :param beliefs_after: only return beliefs formed after this datetime (inclusive)
        :param beliefs_before: only return beliefs formed before this datetime (inclusive)
        :param source: search only beliefs by this source (pass its name or id) or list of sources
        """
        return TimedBelief.search(
            sensor=self,
            event_starts_after=event_starts_after,
            event_ends_before=event_ends_before,
            beliefs_after=beliefs_after,
            beliefs_before=beliefs_before,
            source=source,
        )

    def chart(
        self,
        chart_type: str = "bar_chart",
        event_starts_after: Optional[datetime_type] = None,
        event_ends_before: Optional[datetime_type] = None,
        beliefs_after: Optional[datetime_type] = None,
        beliefs_before: Optional[datetime_type] = None,
        source: Optional[Union[int, List[int], str, List[str]]] = None,
        data_only: bool = False,
        chart_only: bool = True,
        as_html: bool = False,
        dataset_name: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Create a chart showing sensor data.

        :param chart_type: currently only "bar_chart" # todo: where can we properly list the available chart types?
        :param event_starts_after: only return beliefs about events that start after this datetime (inclusive)
        :param event_ends_before: only return beliefs about events that end before this datetime (inclusive)
        :param beliefs_after: only return beliefs formed after this datetime (inclusive)
        :param beliefs_before: only return beliefs formed before this datetime (inclusive)
        :param source: search only beliefs by this source (pass its name or id) or list of sources
        :param data_only: return just the data (in case you have the chart specs already)
        :param as_html: return the chart with data as a standalone html
        :param dataset_name: optionally name the dataset used in the chart (the default name is sensor_<id>)
        """

        # Set up chart specification
        if dataset_name is None:
            dataset_name = "sensor_" + str(self.id)
        self.sensor_type = (
            self.name
        )  # todo remove this placeholder when sensor types are modelled
        chart = belief_charts_mapping[chart_type](
            title=capitalize(self.name),
            quantity=capitalize(self.sensor_type),
            unit=self.unit,
            dataset_name=dataset_name,
            **kwargs,
        )
        if chart_only:
            return json.dumps(chart)

        # Set up data
        bdf = self.search_beliefs(
            event_starts_after=event_starts_after,
            event_ends_before=event_ends_before,
            beliefs_after=beliefs_after,
            beliefs_before=beliefs_before,
            source=source,
        )
        df = bdf.reset_index()
        df["source"] = df["source"].apply(lambda x: x.name)
        data = df.to_json(orient="records")
        if data_only:
            return data

        # Combine chart specs and data
        chart["datasets"] = {dataset_name: json.loads(data)}
        if as_html:
            return spec_to_html(
                chart,
                "vega-lite",
                vega_version="5",
                vegaembed_version="6.17.0",
                vegalite_version="5.0.0",
            )
        return json.dumps(chart)

    @property
    def timerange(self) -> Dict[str, datetime_type]:
        """Timerange for which sensor data exists.

        :returns: dictionary with start and end, for example:
                  {
                      'start': datetime.datetime(2020, 12, 3, 14, 0, tzinfo=pytz.utc),
                      'end': datetime.datetime(2020, 12, 3, 14, 30, tzinfo=pytz.utc)
                  }
        """
        least_recent_query = (
            TimedBelief.query.filter(TimedBelief.sensor == self)
            .order_by(TimedBelief.event_start.asc())
            .limit(1)
        )
        most_recent_query = (
            TimedBelief.query.filter(TimedBelief.sensor == self)
            .order_by(TimedBelief.event_start.desc())
            .limit(1)
        )
        results = least_recent_query.union_all(most_recent_query).all()
        if not results:
            # return now in case there is no data for the sensor
            now = server_now()
            return dict(start=now, end=now)
        least_recent, most_recent = results
        return dict(start=least_recent.event_start, end=most_recent.event_end)

    def __repr__(self) -> str:
        return f"<Sensor {self.id}: {self.name}>"


class TimedBelief(db.Model, tb.TimedBeliefDBMixin):
    """A timed belief holds a precisely timed record of a belief about an event.

    It also records the source of the belief, and the sensor that the event pertains to.
    """

    @declared_attr
    def source_id(cls):
        return db.Column(db.Integer, db.ForeignKey("data_source.id"), primary_key=True)

    sensor = db.relationship("Sensor", backref=db.backref("beliefs", lazy=True))
    source = db.relationship("DataSource", backref=db.backref("beliefs", lazy=True))

    def __init__(
        self,
        sensor: tb.DBSensor,
        source: tb.DBBeliefSource,
        **kwargs,
    ):
        tb.TimedBeliefDBMixin.__init__(self, sensor, source, **kwargs)
        tb_utils.remove_class_init_kwargs(tb.TimedBeliefDBMixin, kwargs)
        db.Model.__init__(self, **kwargs)

    @classmethod
    def search(
        cls,
        sensor: Sensor,
        event_starts_after: Optional[datetime_type] = None,
        event_ends_before: Optional[datetime_type] = None,
        beliefs_after: Optional[datetime_type] = None,
        beliefs_before: Optional[datetime_type] = None,
        source: Optional[Union[int, List[int], str, List[str]]] = None,
    ) -> tb.BeliefsDataFrame:
        """Search all beliefs about events for a given sensor.

        :param sensor: search only this sensor
        :param event_starts_after: only return beliefs about events that start after this datetime (inclusive)
        :param event_ends_before: only return beliefs about events that end before this datetime (inclusive)
        :param beliefs_after: only return beliefs formed after this datetime (inclusive)
        :param beliefs_before: only return beliefs formed before this datetime (inclusive)
        :param source: search only beliefs by this source (pass its name or id) or list of sources
        """
        return cls.search_session(
            session=db.session,
            sensor=sensor,
            event_starts_after=event_starts_after,
            event_ends_before=event_ends_before,
            beliefs_after=beliefs_after,
            beliefs_before=beliefs_before,
            source=source,
        )

    @classmethod
    def add(cls, bdf: tb.BeliefsDataFrame, commit_transaction: bool = True):
        """Add a BeliefsDataFrame as timed beliefs in the database.

        :param bdf: the BeliefsDataFrame to be persisted
        :param commit_transaction: if True, the session is committed
                                   if False, you can still add other data to the session
                                   and commit it all within an atomic transaction
        """
        return cls.add_to_session(
            session=db.session,
            beliefs_data_frame=bdf,
            commit_transaction=commit_transaction,
        )

    def __repr__(self) -> str:
        """timely-beliefs representation of timed beliefs."""
        return tb.TimedBelief.__repr__(self)


class SensorSchemaMixin(Schema):
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


class SensorSchema(SensorSchemaMixin, ma.SQLAlchemySchema):
    """
    Sensor schema, with validations.
    """

    class Meta:
        model = Sensor


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
