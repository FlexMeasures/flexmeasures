from typing import Any, List, Dict, Optional, Union, Type, Tuple
from datetime import datetime as datetime_type, timedelta
import json

from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Query, Session
import timely_beliefs as tb
from timely_beliefs.beliefs.probabilistic_utils import get_median_belief
import timely_beliefs.utils as tb_utils

from flexmeasures.auth.policy import AuthModelMixin, EVERY_LOGGED_IN_USER
from flexmeasures.data import db
from flexmeasures.data.models.parsing_utils import parse_source_arg
from flexmeasures.data.queries.utils import (
    create_beliefs_query,
    get_belief_timing_criteria,
    get_source_criteria,
)
from flexmeasures.data.services.time_series import (
    collect_time_series_data,
    aggregate_values,
)
from flexmeasures.utils.entity_address_utils import build_entity_address
from flexmeasures.utils.unit_utils import is_energy_unit, is_power_unit
from flexmeasures.data.models.annotations import (
    Annotation,
    SensorAnnotationRelationship,
)
from flexmeasures.data.models.charts import chart_type_to_chart_specs
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.validation_utils import check_required_attributes
from flexmeasures.utils.time_utils import server_now


class Sensor(db.Model, tb.SensorDBMixin, AuthModelMixin):
    """A sensor measures events."""

    attributes = db.Column(MutableDict.as_mutable(db.JSON), nullable=False, default={})

    generic_asset_id = db.Column(
        db.Integer,
        db.ForeignKey("generic_asset.id", ondelete="CASCADE"),
        nullable=False,
    )
    generic_asset = db.relationship(
        "GenericAsset",
        foreign_keys=[generic_asset_id],
        backref=db.backref(
            "sensors", lazy=True, cascade="all, delete-orphan", passive_deletes=True
        ),
    )
    annotations = db.relationship(
        "Annotation",
        secondary="annotations_sensors",
        backref=db.backref("sensors", lazy="dynamic"),
    )

    def __init__(
        self,
        name: str,
        generic_asset: Optional[GenericAsset] = None,
        generic_asset_id: Optional[int] = None,
        attributes: Optional[dict] = None,
        **kwargs,
    ):
        assert (generic_asset is None) ^ (
            generic_asset_id is None
        ), "Either generic_asset_id or generic_asset must be set."
        tb.SensorDBMixin.__init__(self, name, **kwargs)
        tb_utils.remove_class_init_kwargs(tb.SensorDBMixin, kwargs)
        if generic_asset is not None:
            kwargs["generic_asset"] = generic_asset
        else:
            kwargs["generic_asset_id"] = generic_asset_id
        if attributes is not None:
            kwargs["attributes"] = attributes
        db.Model.__init__(self, **kwargs)

    def __acl__(self):
        """
        All logged-in users can read if the sensor belongs to a public asset.
        Within same account, everyone can read and update.
        Creation and deletion are left to account admins.
        """
        return {
            "create-children": (
                f"account:{self.generic_asset.account_id}",
                "role:account-admin",
            ),
            "read": f"account:{self.generic_asset.account_id}"
            if self.generic_asset.account_id is not None
            else EVERY_LOGGED_IN_USER,
            "update": f"account:{self.generic_asset.account_id}",
            "delete": (
                f"account:{self.generic_asset.account_id}",
                "role:account-admin",
            ),
        }

    @property
    def entity_address(self) -> str:
        return build_entity_address(dict(sensor_id=self.id), "sensor")

    @property
    def location(self) -> Optional[Tuple[float, float]]:
        location = (self.get_attribute("latitude"), self.get_attribute("longitude"))
        if None not in location:
            return location

    @property
    def measures_power(self) -> bool:
        """True if this sensor's unit is measuring power"""
        return is_power_unit(self.unit)

    @property
    def measures_energy(self) -> bool:
        """True if this sensor's unit is measuring energy"""
        return is_energy_unit(self.unit)

    @property
    def is_strictly_non_positive(self) -> bool:
        """Return True if this sensor strictly records non-positive values."""
        return self.get_attribute("is_consumer", False) and not self.get_attribute(
            "is_producer", True
        )

    @property
    def is_strictly_non_negative(self) -> bool:
        """Return True if this sensor strictly records non-negative values."""
        return self.get_attribute("is_producer", False) and not self.get_attribute(
            "is_consumer", True
        )

    def get_attribute(self, attribute: str, default: Any = None) -> Any:
        """Looks for the attribute on the Sensor.
        If not found, looks for the attribute on the Sensor's GenericAsset.
        If not found, returns the default.
        """
        if hasattr(self, attribute):
            return getattr(self, attribute)
        if attribute in self.attributes:
            return self.attributes[attribute]
        if hasattr(self.generic_asset, attribute):
            return getattr(self.generic_asset, attribute)
        if attribute in self.generic_asset.attributes:
            return self.generic_asset.attributes[attribute]
        return default

    def has_attribute(self, attribute: str) -> bool:
        return (
            attribute in self.attributes or attribute in self.generic_asset.attributes
        )

    def set_attribute(self, attribute: str, value):
        if self.has_attribute(attribute):
            self.attributes[attribute] = value

    def check_required_attributes(
        self,
        attributes: List[Union[str, Tuple[str, Union[Type, Tuple[Type, ...]]]]],
    ):
        """Raises if any attribute in the list of attributes is missing, or has the wrong type.

        :param attributes: List of either an attribute name or a tuple of an attribute name and its allowed type
                           (the allowed type may also be a tuple of several allowed types)
        """
        check_required_attributes(self, attributes)

    def latest_state(
        self,
        source: Optional[
            Union[DataSource, List[DataSource], int, List[int], str, List[str]]
        ] = None,
    ) -> tb.BeliefsDataFrame:
        """Search the most recent event for this sensor, and return the most recent ex-post belief.

        :param source: search only beliefs by this source (pass the DataSource, or its name or id) or list of sources
        """
        return self.search_beliefs(
            horizons_at_most=timedelta(0),
            source=source,
            most_recent_beliefs_only=True,
            most_recent_events_only=True,
            one_deterministic_belief_per_event=True,
        )

    def search_annotations(
        self,
        annotation_starts_after: Optional[datetime_type] = None,
        annotation_ends_before: Optional[datetime_type] = None,
        source: Optional[
            Union[DataSource, List[DataSource], int, List[int], str, List[str]]
        ] = None,
        include_asset_annotations: bool = False,
        include_account_annotations: bool = False,
    ):
        parsed_sources = parse_source_arg(source)
        query = Annotation.query.join(SensorAnnotationRelationship).filter(
            SensorAnnotationRelationship.sensor_id == self.id,
            SensorAnnotationRelationship.annotation_id == Annotation.id,
        )
        if annotation_starts_after is not None:
            query = query.filter(
                Annotation.start >= annotation_starts_after,
            )
        if annotation_ends_before is not None:
            query = query.filter(
                Annotation.end <= annotation_ends_before,
            )
        if parsed_sources:
            query = query.filter(
                Annotation.source.in_(parsed_sources),
            )
        annotations = query.all()
        if include_asset_annotations:
            annotations += self.generic_asset.search_annotations(
                annotation_starts_before=annotation_starts_after,
                annotation_ends_before=annotation_ends_before,
                source=source,
            )
        if include_account_annotations:
            annotations += self.generic_asset.owner.search_annotations(
                annotation_starts_before=annotation_starts_after,
                annotation_ends_before=annotation_ends_before,
                source=source,
            )
        return annotations

    def search_beliefs(
        self,
        event_starts_after: Optional[datetime_type] = None,
        event_ends_before: Optional[datetime_type] = None,
        beliefs_after: Optional[datetime_type] = None,
        beliefs_before: Optional[datetime_type] = None,
        horizons_at_least: Optional[timedelta] = None,
        horizons_at_most: Optional[timedelta] = None,
        source: Optional[
            Union[DataSource, List[DataSource], int, List[int], str, List[str]]
        ] = None,
        most_recent_beliefs_only: bool = True,
        most_recent_events_only: bool = False,
        most_recent_only: bool = None,  # deprecated
        one_deterministic_belief_per_event: bool = False,
        as_json: bool = False,
    ) -> Union[tb.BeliefsDataFrame, str]:
        """Search all beliefs about events for this sensor.

        If you don't set any filters, you get the most recent beliefs about all events.

        :param event_starts_after: only return beliefs about events that start after this datetime (inclusive)
        :param event_ends_before: only return beliefs about events that end before this datetime (inclusive)
        :param beliefs_after: only return beliefs formed after this datetime (inclusive)
        :param beliefs_before: only return beliefs formed before this datetime (inclusive)
        :param horizons_at_least: only return beliefs with a belief horizon equal or greater than this timedelta (for example, use timedelta(0) to get ante knowledge time beliefs)
        :param horizons_at_most: only return beliefs with a belief horizon equal or less than this timedelta (for example, use timedelta(0) to get post knowledge time beliefs)
        :param source: search only beliefs by this source (pass the DataSource, or its name or id) or list of sources
        :param most_recent_beliefs_only: only return the most recent beliefs for each event from each source (minimum belief horizon)
        :param most_recent_events_only: only return (post knowledge time) beliefs for the most recent event (maximum event start)
        :param one_deterministic_belief_per_event: only return a single value per event (no probabilistic distribution)
        :param as_json: return beliefs in JSON format (e.g. for use in charts) rather than as BeliefsDataFrame
        :returns: BeliefsDataFrame or JSON string (if as_json is True)
        """
        # todo: deprecate the 'most_recent_only' argument in favor of 'most_recent_beliefs_only' (announced v0.8.0)
        most_recent_beliefs_only = tb_utils.replace_deprecated_argument(
            "most_recent_only",
            most_recent_only,
            "most_recent_beliefs_only",
            most_recent_beliefs_only,
            required_argument=False,
        )
        bdf = TimedBelief.search(
            sensors=self,
            event_starts_after=event_starts_after,
            event_ends_before=event_ends_before,
            beliefs_after=beliefs_after,
            beliefs_before=beliefs_before,
            horizons_at_least=horizons_at_least,
            horizons_at_most=horizons_at_most,
            source=source,
            most_recent_beliefs_only=most_recent_beliefs_only,
            most_recent_events_only=most_recent_events_only,
            one_deterministic_belief_per_event=one_deterministic_belief_per_event,
        )
        if as_json:
            df = bdf.reset_index()
            df["source"] = df["source"].astype(str)
            return df.to_json(orient="records")
        return bdf

    def chart(
        self,
        chart_type: str = "bar_chart",
        event_starts_after: Optional[datetime_type] = None,
        event_ends_before: Optional[datetime_type] = None,
        beliefs_after: Optional[datetime_type] = None,
        beliefs_before: Optional[datetime_type] = None,
        source: Optional[
            Union[DataSource, List[DataSource], int, List[int], str, List[str]]
        ] = None,
        most_recent_beliefs_only: bool = True,
        include_data: bool = False,
        dataset_name: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Create a chart showing sensor data.

        :param chart_type: currently only "bar_chart" # todo: where can we properly list the available chart types?
        :param event_starts_after: only return beliefs about events that start after this datetime (inclusive)
        :param event_ends_before: only return beliefs about events that end before this datetime (inclusive)
        :param beliefs_after: only return beliefs formed after this datetime (inclusive)
        :param beliefs_before: only return beliefs formed before this datetime (inclusive)
        :param source: search only beliefs by this source (pass the DataSource, or its name or id) or list of sources
        :param most_recent_beliefs_only: only return the most recent beliefs for each event from each source (minimum belief horizon)
        :param include_data: if True, include data in the chart, or if False, exclude data
        :param dataset_name: optionally name the dataset used in the chart (the default name is sensor_<id>)
        """

        # Set up chart specification
        if dataset_name is None:
            dataset_name = "sensor_" + str(self.id)
        self.sensor_type = (
            self.name
        )  # todo remove this placeholder when sensor types are modelled
        chart_specs = chart_type_to_chart_specs(
            chart_type,
            sensor=self,
            dataset_name=dataset_name,
            **kwargs,
        )

        if include_data:
            # Set up data
            data = self.search_beliefs(
                as_json=True,
                event_starts_after=event_starts_after,
                event_ends_before=event_ends_before,
                beliefs_after=beliefs_after,
                beliefs_before=beliefs_before,
                most_recent_beliefs_only=most_recent_beliefs_only,
                source=source,
            )
            # Combine chart specs and data
            chart_specs["datasets"] = {dataset_name: json.loads(data)}
        return chart_specs

    @property
    def timerange(self) -> Dict[str, datetime_type]:
        """Time range for which sensor data exists.

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
        return f"<Sensor {self.id}: {self.name}, unit: {self.unit} res.: {self.event_resolution}>"


class TimedBelief(db.Model, tb.TimedBeliefDBMixin):
    """A timed belief holds a precisely timed record of a belief about an event.

    It also records the source of the belief, and the sensor that the event pertains to.
    """

    @declared_attr
    def source_id(cls):
        return db.Column(db.Integer, db.ForeignKey("data_source.id"), primary_key=True)

    sensor = db.relationship(
        "Sensor",
        backref=db.backref(
            "beliefs",
            lazy=True,
            cascade="merge",  # no save-update (i.e. don't auto-save time series data to session upon updating sensor)
        ),
    )
    source = db.relationship(
        "DataSource",
        backref=db.backref(
            "beliefs",
            lazy=True,
            cascade="merge",  # no save-update (i.e. don't auto-save time series data to session upon updating source)
        ),
    )

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
        sensors: Union[Sensor, int, str, List[Union[Sensor, int, str]]],
        sensor: Sensor = None,  # deprecated
        event_starts_after: Optional[datetime_type] = None,
        event_ends_before: Optional[datetime_type] = None,
        beliefs_after: Optional[datetime_type] = None,
        beliefs_before: Optional[datetime_type] = None,
        horizons_at_least: Optional[timedelta] = None,
        horizons_at_most: Optional[timedelta] = None,
        source: Optional[
            Union[DataSource, List[DataSource], int, List[int], str, List[str]]
        ] = None,
        user_source_ids: Optional[Union[int, List[int]]] = None,
        source_types: Optional[List[str]] = None,
        exclude_source_types: Optional[List[str]] = None,
        most_recent_beliefs_only: bool = True,
        most_recent_events_only: bool = False,
        most_recent_only: bool = None,  # deprecated
        one_deterministic_belief_per_event: bool = False,
        resolution: Union[str, timedelta] = None,
        sum_multiple: bool = True,
    ) -> Union[tb.BeliefsDataFrame, Dict[str, tb.BeliefsDataFrame]]:
        """Search all beliefs about events for the given sensors.

        If you don't set any filters, you get the most recent beliefs about all events.

        :param sensors: search only these sensors, identified by their instance or id (both unique) or name (non-unique)
        :param event_starts_after: only return beliefs about events that start after this datetime (inclusive)
        :param event_ends_before: only return beliefs about events that end before this datetime (inclusive)
        :param beliefs_after: only return beliefs formed after this datetime (inclusive)
        :param beliefs_before: only return beliefs formed before this datetime (inclusive)
        :param horizons_at_least: only return beliefs with a belief horizon equal or greater than this timedelta (for example, use timedelta(0) to get ante knowledge time beliefs)
        :param horizons_at_most: only return beliefs with a belief horizon equal or less than this timedelta (for example, use timedelta(0) to get post knowledge time beliefs)
        :param source: search only beliefs by this source (pass the DataSource, or its name or id) or list of sources
        :param user_source_ids: Optional list of user source ids to query only specific user sources
        :param source_types: Optional list of source type names to query only specific source types *
        :param exclude_source_types: Optional list of source type names to exclude specific source types *
        :param most_recent_beliefs_only: only return the most recent beliefs for each event from each source (minimum belief horizon)
        :param most_recent_events_only: only return (post knowledge time) beliefs for the most recent event (maximum event start)
        :param one_deterministic_belief_per_event: only return a single value per event (no probabilistic distribution)
        :param resolution: Optional timedelta or pandas freqstr used to resample the results **
        :param sum_multiple: if True, sum over multiple sensors; otherwise, return a dictionary with sensor names as key, each holding a BeliefsDataFrame as its value

        *  If user_source_ids is specified, the "user" source type is automatically included (and not excluded).
           Somewhat redundant, though still allowed, is to set both source_types and exclude_source_types.
        ** Note that timely-beliefs converts string resolutions to datetime.timedelta objects (see https://github.com/SeitaBV/timely-beliefs/issues/13).
        """
        # todo: deprecate the 'sensor' argument in favor of 'sensors' (announced v0.8.0)
        sensors = tb_utils.replace_deprecated_argument(
            "sensor",
            sensor,
            "sensors",
            sensors,
        )
        # todo: deprecate the 'most_recent_only' argument in favor of 'most_recent_beliefs_only' (announced v0.8.0)
        most_recent_beliefs_only = tb_utils.replace_deprecated_argument(
            "most_recent_only",
            most_recent_only,
            "most_recent_beliefs_only",
            most_recent_beliefs_only,
            required_argument=False,
        )

        # convert to list
        sensors = [sensors] if not isinstance(sensors, list) else sensors

        # convert from sensor names to sensors
        sensor_names = [s for s in sensors if isinstance(s, str)]
        if sensor_names:
            sensors = [s for s in sensors if not isinstance(s, str)]
            sensors_from_names = Sensor.query.filter(
                Sensor.name.in_(sensor_names)
            ).all()
            sensors.extend(sensors_from_names)

        parsed_sources = parse_source_arg(source)
        source_criteria = get_source_criteria(
            cls, user_source_ids, source_types, exclude_source_types
        )
        custom_join_targets = [] if parsed_sources else [DataSource]

        bdf_dict = {}
        for sensor in sensors:
            bdf = cls.search_session(
                session=db.session,
                sensor=sensor,
                event_starts_after=event_starts_after,
                event_ends_before=event_ends_before,
                beliefs_after=beliefs_after,
                beliefs_before=beliefs_before,
                horizons_at_least=horizons_at_least,
                horizons_at_most=horizons_at_most,
                source=parsed_sources,
                most_recent_beliefs_only=most_recent_beliefs_only,
                most_recent_events_only=most_recent_events_only,
                custom_filter_criteria=source_criteria,
                custom_join_targets=custom_join_targets,
            )
            if one_deterministic_belief_per_event:
                # todo: compute median of collective belief instead of median of first belief (update expected test results accordingly)
                # todo: move to timely-beliefs: select mean/median belief
                bdf = (
                    bdf.for_each_belief(get_median_belief)
                    .groupby(level=["event_start", "belief_time"])
                    .apply(lambda x: x.head(1))
                )
            if resolution is not None:
                bdf = bdf.resample_events(
                    resolution, keep_only_most_recent_belief=most_recent_beliefs_only
                )
            bdf_dict[bdf.sensor.name] = bdf

        if sum_multiple:
            return aggregate_values(bdf_dict)
        else:
            return bdf_dict

    @classmethod
    def add(
        cls,
        bdf: tb.BeliefsDataFrame,
        expunge_session: bool = False,
        allow_overwrite: bool = False,
        bulk_save_objects: bool = False,
        commit_transaction: bool = False,
    ):
        """Add a BeliefsDataFrame as timed beliefs in the database.

        :param bdf: the BeliefsDataFrame to be persisted
        :param expunge_session:     if True, all non-flushed instances are removed from the session before adding beliefs.
                                    Expunging can resolve problems you might encounter with states of objects in your session.
                                    When using this option, you might want to flush newly-created objects which are not beliefs
                                    (e.g. a sensor or data source object).
        :param allow_overwrite:     if True, new objects are merged
                                    if False, objects are added to the session or bulk saved
        :param bulk_save_objects:   if True, objects are bulk saved with session.bulk_save_objects(),
                                    which is quite fast but has several caveats, see:
                                    https://docs.sqlalchemy.org/orm/persistence_techniques.html#bulk-operations-caveats
                                    if False, objects are added to the session with session.add_all()
        :param commit_transaction:  if True, the session is committed
                                    if False, you can still add other data to the session
                                    and commit it all within an atomic transaction
        """
        return cls.add_to_session(
            session=db.session,
            beliefs_data_frame=bdf,
            expunge_session=expunge_session,
            allow_overwrite=allow_overwrite,
            bulk_save_objects=bulk_save_objects,
            commit_transaction=commit_transaction,
        )

    def __repr__(self) -> str:
        """timely-beliefs representation of timed beliefs."""
        return tb.TimedBelief.__repr__(self)


class TimedValue(object):
    """
    A mixin of all tables that store time series data, either forecasts or measurements.
    Represents one row.

    Note: This will be deprecated in favour of Timely-Beliefs - based code (see Sensor/TimedBelief)
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
        old_sensor_names: Tuple[str],
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
          Somewhat redundant, though still allowed, is to set both source_types and exclude_source_types.


        # todo: add examples
        # todo: switch to using timely_beliefs queries, which are more powerful
        """
        if session is None:
            session = db.session
        start, end = query_window
        query = create_beliefs_query(cls, session, Sensor, old_sensor_names, start, end)
        belief_timing_criteria = get_belief_timing_criteria(
            cls, Sensor, belief_horizon_window, belief_time_window
        )
        source_criteria = get_source_criteria(
            cls, user_source_ids, source_types, exclude_source_types
        )
        return query.filter(*belief_timing_criteria, *source_criteria)

    @classmethod
    def search(
        cls,
        old_sensor_names: Union[str, List[str]],
        event_starts_after: Optional[datetime_type] = None,
        event_ends_before: Optional[datetime_type] = None,
        horizons_at_least: Optional[timedelta] = None,
        horizons_at_most: Optional[timedelta] = None,
        beliefs_after: Optional[datetime_type] = None,
        beliefs_before: Optional[datetime_type] = None,
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
            old_sensor_names=old_sensor_names,
            make_query=cls.make_query,
            query_window=(event_starts_after, event_ends_before),
            belief_horizon_window=(horizons_at_least, horizons_at_most),
            belief_time_window=(beliefs_after, beliefs_before),
            user_source_ids=user_source_ids,
            source_types=source_types,
            exclude_source_types=exclude_source_types,
            resolution=resolution,
            sum_multiple=sum_multiple,
        )
