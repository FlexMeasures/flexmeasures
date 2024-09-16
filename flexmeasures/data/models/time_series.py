from __future__ import annotations

from typing import Any, Type
from datetime import datetime as datetime_type, timedelta
import json
from flask import current_app

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy import inspect
import timely_beliefs as tb
from timely_beliefs.beliefs.probabilistic_utils import get_median_belief
import timely_beliefs.utils as tb_utils

from flexmeasures.auth.policy import AuthModelMixin
from flexmeasures.data import db
from flexmeasures.data.models.parsing_utils import parse_source_arg
from flexmeasures.data.services.annotations import prepare_annotations_for_chart
from flexmeasures.data.services.timerange import get_timerange
from flexmeasures.data.queries.utils import get_source_criteria
from flexmeasures.data.services.time_series import aggregate_values
from flexmeasures.utils.entity_address_utils import (
    EntityAddressException,
    build_entity_address,
)
from flexmeasures.utils.unit_utils import (
    is_energy_unit,
    is_power_unit,
    is_energy_price_unit,
)
from flexmeasures.data.models.annotations import (
    Annotation,
    SensorAnnotationRelationship,
    to_annotation_frame,
)
from flexmeasures.data.models.charts import chart_type_to_chart_specs
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.validation_utils import check_required_attributes
from flexmeasures.data.queries.sensors import query_sensors_by_proximity
from flexmeasures.utils.geo_utils import parse_lat_lng


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

    def get_path(self, separator: str = ">"):
        return (
            f"{self.generic_asset.get_path(separator=separator)}{separator}{self.name}"
        )

    def __init__(
        self,
        name: str,
        generic_asset: GenericAsset | None = None,
        generic_asset_id: int | None = None,
        attributes: dict | None = None,
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

    __table_args__ = (
        UniqueConstraint(
            "name",
            "generic_asset_id",
            name="sensor_name_generic_asset_id_key",
        ),
    )

    def __acl__(self):
        """
        We allow reading to whoever can read the asset.
        Editing as well as deletion is left to account admins.
        """
        return {
            "create-children": f"account:{self.generic_asset.account_id}",
            "read": self.generic_asset.__acl__()["read"],
            "update": (
                f"account:{self.generic_asset.account_id}",
                "role:account-admin",
            ),
            "delete": (
                f"account:{self.generic_asset.account_id}",
                "role:account-admin",
            ),
        }

    @property
    def entity_address(self) -> str:
        try:
            return build_entity_address(dict(sensor_id=self.id), "sensor")
        except EntityAddressException as eae:
            current_app.logger.warn(
                f"Problems generating entity address for sensor {self}: {eae}"
            )
            return "no entity address available"

    @property
    def location(self) -> tuple[float, float] | None:
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
    def measures_energy_price(self) -> bool:
        """True if this sensors' unit is measuring energy prices"""
        return is_energy_price_unit(self.unit)

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
        attributes: list[str | tuple[str, Type | tuple[Type, ...]]],
    ):
        """Raises if any attribute in the list of attributes is missing, or has the wrong type.

        :param attributes: List of either an attribute name or a tuple of an attribute name and its allowed type
                           (the allowed type may also be a tuple of several allowed types)
        """
        check_required_attributes(self, attributes)

    def latest_state(
        self,
        source: DataSource
        | list[DataSource]
        | int
        | list[int]
        | str
        | list[str]
        | None = None,
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
        annotation_starts_after: datetime_type | None = None,  # deprecated
        annotations_after: datetime_type | None = None,
        annotation_ends_before: datetime_type | None = None,  # deprecated
        annotations_before: datetime_type | None = None,
        source: DataSource
        | list[DataSource]
        | int
        | list[int]
        | str
        | list[str]
        | None = None,
        include_asset_annotations: bool = False,
        include_account_annotations: bool = False,
        as_frame: bool = False,
    ) -> list[Annotation] | pd.DataFrame:
        """Return annotations assigned to this sensor, and optionally, also those assigned to the sensor's asset and the asset's account.

        :param annotations_after: only return annotations that end after this datetime (exclusive)
        :param annotations_before: only return annotations that start before this datetime (exclusive)
        """

        # todo: deprecate the 'annotation_starts_after' argument in favor of 'annotations_after' (announced v0.11.0)
        annotations_after = tb_utils.replace_deprecated_argument(
            "annotation_starts_after",
            annotation_starts_after,
            "annotations_after",
            annotations_after,
            required_argument=False,
        )

        # todo: deprecate the 'annotation_ends_before' argument in favor of 'annotations_before' (announced v0.11.0)
        annotations_before = tb_utils.replace_deprecated_argument(
            "annotation_ends_before",
            annotation_ends_before,
            "annotations_before",
            annotations_before,
            required_argument=False,
        )

        parsed_sources = parse_source_arg(source)
        query = (
            select(Annotation)
            .join(SensorAnnotationRelationship)
            .filter(
                SensorAnnotationRelationship.sensor_id == self.id,
                SensorAnnotationRelationship.annotation_id == Annotation.id,
            )
        )
        if annotations_after is not None:
            query = query.filter(
                Annotation.end > annotations_after,
            )
        if annotations_before is not None:
            query = query.filter(
                Annotation.start < annotations_before,
            )
        if parsed_sources:
            query = query.filter(
                Annotation.source.in_(parsed_sources),
            )
        annotations = db.session.scalars(query).all()
        if include_asset_annotations:
            annotations += self.generic_asset.search_annotations(
                annotations_after=annotations_after,
                annotations_before=annotations_before,
                source=source,
            )
        if include_account_annotations:
            annotations += self.generic_asset.owner.search_annotations(
                annotations_after=annotations_after,
                annotations_before=annotations_before,
                source=source,
            )

        return to_annotation_frame(annotations) if as_frame else annotations

    def search_beliefs(
        self,
        event_starts_after: datetime_type | None = None,
        event_ends_before: datetime_type | None = None,
        beliefs_after: datetime_type | None = None,
        beliefs_before: datetime_type | None = None,
        horizons_at_least: timedelta | None = None,
        horizons_at_most: timedelta | None = None,
        source: DataSource
        | list[DataSource]
        | int
        | list[int]
        | str
        | list[str]
        | None = None,
        most_recent_beliefs_only: bool = True,
        most_recent_events_only: bool = False,
        most_recent_only: bool = False,
        one_deterministic_belief_per_event: bool = False,
        one_deterministic_belief_per_event_per_source: bool = False,
        as_json: bool = False,
        resolution: str | timedelta | None = None,
    ) -> tb.BeliefsDataFrame | str:
        """Search all beliefs about events for this sensor.

        If you don't set any filters, you get the most recent beliefs about all events.

        :param event_starts_after: only return beliefs about events that start after this datetime (inclusive)
        :param event_ends_before: only return beliefs about events that end before this datetime (inclusive)
        :param beliefs_after: only return beliefs formed after this datetime (inclusive)
        :param beliefs_before: only return beliefs formed before this datetime (inclusive)
        :param horizons_at_least: only return beliefs with a belief horizon equal or greater than this timedelta (for example, use timedelta(0) to get ante knowledge time beliefs)
        :param horizons_at_most: only return beliefs with a belief horizon equal or less than this timedelta (for example, use timedelta(0) to get post knowledge time beliefs)
        :param source: search only beliefs by this source (pass the DataSource, or its name or id) or list of sources. Without this set and a most recent parameter used (see below), the results can be of any source.
        :param most_recent_beliefs_only: only return the most recent beliefs for each event from each source (minimum belief horizon). Defaults to True.
        :param most_recent_events_only: only return (post knowledge time) beliefs for the most recent event (maximum event start). Defaults to False.
        :param most_recent_only: only return a single belief, the most recent from the most recent event. Fastest method if you only need one. Defaults to False. To use, also set most_recent_beliefs_only=False. Use with care when data uses cumulative probability (more than one belief per event_start and horizon).
        :param one_deterministic_belief_per_event: only return a single value per event (no probabilistic distribution and only 1 source)
        :param one_deterministic_belief_per_event_per_source: only return a single value per event per source (no probabilistic distribution)
        :param as_json: return beliefs in JSON format (e.g. for use in charts) rather than as BeliefsDataFrame
        :param resolution: optionally set the resolution of data being displayed
        :returns: BeliefsDataFrame or JSON string (if as_json is True)
        """
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
            most_recent_only=most_recent_only,
            one_deterministic_belief_per_event=one_deterministic_belief_per_event,
            one_deterministic_belief_per_event_per_source=one_deterministic_belief_per_event_per_source,
            resolution=resolution,
        )
        if as_json:
            df = bdf.reset_index()
            df["sensor"] = self
            df["sensor"] = df["sensor"].apply(lambda x: x.to_dict())
            df["source"] = df["source"].apply(lambda x: x.to_dict())
            return df.to_json(orient="records")
        return bdf

    def chart(
        self,
        chart_type: str = "bar_chart",
        event_starts_after: datetime_type | None = None,
        event_ends_before: datetime_type | None = None,
        beliefs_after: datetime_type | None = None,
        beliefs_before: datetime_type | None = None,
        source: DataSource
        | list[DataSource]
        | int
        | list[int]
        | str
        | list[str]
        | None = None,
        most_recent_beliefs_only: bool = True,
        include_data: bool = False,
        include_sensor_annotations: bool = False,
        include_asset_annotations: bool = False,
        include_account_annotations: bool = False,
        dataset_name: str | None = None,
        resolution: str | timedelta | None = None,
        **kwargs,
    ) -> dict:
        """Create a vega-lite chart showing sensor data.

        :param chart_type: currently only "bar_chart" # todo: where can we properly list the available chart types?
        :param event_starts_after: only return beliefs about events that start after this datetime (inclusive)
        :param event_ends_before: only return beliefs about events that end before this datetime (inclusive)
        :param beliefs_after: only return beliefs formed after this datetime (inclusive)
        :param beliefs_before: only return beliefs formed before this datetime (inclusive)
        :param source: search only beliefs by this source (pass the DataSource, or its name or id) or list of sources
        :param most_recent_beliefs_only: only return the most recent beliefs for each event from each source (minimum belief horizon)
        :param include_data: if True, include data in the chart, or if False, exclude data
        :param include_sensor_annotations: if True and include_data is True, include sensor annotations in the chart, or if False, exclude these
        :param include_asset_annotations: if True and include_data is True, include asset annotations in the chart, or if False, exclude them
        :param include_account_annotations: if True and include_data is True, include account annotations in the chart, or if False, exclude them
        :param dataset_name: optionally name the dataset used in the chart (the default name is sensor_<id>)
        :param resolution: optionally set the resolution of data being displayed
        :returns: JSON string defining vega-lite chart specs
        """

        # Set up chart specification
        if dataset_name is None:
            dataset_name = "sensor_" + str(self.id)
        self.sensor_type = self.get_attribute("sensor_type", self.name)
        if event_starts_after:
            kwargs["event_starts_after"] = event_starts_after
        if event_ends_before:
            kwargs["event_ends_before"] = event_ends_before
        chart_specs = chart_type_to_chart_specs(
            chart_type,
            sensor=self,
            dataset_name=dataset_name,
            include_annotations=include_sensor_annotations
            or include_asset_annotations
            or include_account_annotations,
            **kwargs,
        )

        if include_data:
            # Get data
            data = self.search_beliefs(
                as_json=True,
                event_starts_after=event_starts_after,
                event_ends_before=event_ends_before,
                beliefs_after=beliefs_after,
                beliefs_before=beliefs_before,
                most_recent_beliefs_only=most_recent_beliefs_only,
                source=source,
                resolution=resolution,
            )

            # Get annotations
            if include_sensor_annotations:
                annotations_df = self.search_annotations(
                    annotations_after=event_starts_after,
                    annotations_before=event_ends_before,
                    include_asset_annotations=include_asset_annotations,
                    include_account_annotations=include_account_annotations,
                    as_frame=True,
                )
            elif include_asset_annotations:
                annotations_df = self.generic_asset.search_annotations(
                    annotations_after=event_starts_after,
                    annotations_before=event_ends_before,
                    include_account_annotations=include_account_annotations,
                    as_frame=True,
                )
            elif include_account_annotations:
                annotations_df = self.generic_asset.owner.search_annotations(
                    annotations_after=event_starts_after,
                    annotations_before=event_ends_before,
                    as_frame=True,
                )
            else:
                annotations_df = to_annotation_frame([])

            # Wrap and stack annotations
            annotations_df = prepare_annotations_for_chart(annotations_df)

            # Annotations to JSON records
            annotations_df = annotations_df.reset_index()
            annotations_df["source"] = annotations_df["source"].astype(str)
            annotations_data = annotations_df.to_json(orient="records")

            # Combine chart specs, data and annotations
            chart_specs["datasets"] = {
                dataset_name: json.loads(data),
                dataset_name + "_annotations": json.loads(annotations_data),
            }

        return chart_specs

    @property
    def timerange(self) -> dict[str, datetime_type]:
        """Time range for which sensor data exists.

        :returns: dictionary with start and end, for example:
                  {
                      'start': datetime.datetime(2020, 12, 3, 14, 0, tzinfo=pytz.utc),
                      'end': datetime.datetime(2020, 12, 3, 14, 30, tzinfo=pytz.utc)
                  }
        """
        start, end = get_timerange([self.id])
        return dict(start=start, end=end)

    def __repr__(self) -> str:
        return f"<Sensor {self.id}: {self.name}, unit: {self.unit} res.: {self.event_resolution}>"

    def __str__(self) -> str:
        return self.name

    def to_dict(self) -> dict:
        return dict(
            id=self.id,
            name=self.name,
            description=f"{self.name} ({self.generic_asset.name})",
        )

    @classmethod
    def find_closest(
        cls, generic_asset_type_name: str, sensor_name: str, n: int = 1, **kwargs
    ) -> "Sensor" | list["Sensor"] | None:
        """Returns the closest n sensors within a given asset type (as a list if n > 1).
        Parses latitude and longitude values stated in kwargs.

        Can be called with an object that has latitude and longitude properties, for example:

            sensor = Sensor.find_closest("weather station", "wind speed", object=generic_asset)

        Can also be called with latitude and longitude parameters, for example:

            sensor = Sensor.find_closest("weather station", "temperature", latitude=32, longitude=54)
            sensor = Sensor.find_closest("weather station", "temperature", lat=32, lng=54)

        Finally, pass in an account_id parameter if you want to query an account other than your own. This only works for admins. Public assets are always queried.
        """

        latitude, longitude = parse_lat_lng(kwargs)
        account_id_filter = kwargs["account_id"] if "account_id" in kwargs else None
        query = query_sensors_by_proximity(
            latitude=latitude,
            longitude=longitude,
            generic_asset_type_name=generic_asset_type_name,
            sensor_name=sensor_name,
            account_id=account_id_filter,
        )
        if n == 1:
            return db.session.scalars(query.limit(1)).first()
        else:
            return db.session.scalars(query.limit(n)).all()

    def make_hashable(self) -> tuple:
        """Returns a tuple with the properties subject to change
        In principle all properties (except ID) of a given sensor could be changed, but not all changes are relevant to warrant reanalysis (e.g. scheduling or forecasting).
        """

        return (self.id, self.attributes, self.generic_asset.attributes)

    def search_data_sources(
        self,
        event_starts_after: datetime_type | None = None,
        event_ends_after: datetime_type | None = None,
        event_starts_before: datetime_type | None = None,
        event_ends_before: datetime_type | None = None,
        source_types: list[str] | None = None,
        exclude_source_types: list[str] | None = None,
    ) -> list[DataSource]:

        q = select(DataSource).join(TimedBelief).filter(TimedBelief.sensor == self)

        # todo: refactor to use apply_event_timing_filters from timely-beliefs
        if event_starts_after:
            q = q.filter(TimedBelief.event_start >= event_starts_after)

        if not pd.isnull(event_ends_after):
            if self.event_resolution == timedelta(0):
                # inclusive
                q = q.filter(TimedBelief.event_start >= event_ends_after)
            else:
                # exclusive
                q = q.filter(
                    TimedBelief.event_start > event_ends_after - self.event_resolution
                )

        if not pd.isnull(event_starts_before):
            if self.event_resolution == timedelta(0):
                # inclusive
                q = q.filter(TimedBelief.event_start <= event_starts_before)
            else:
                # exclusive
                q = q.filter(TimedBelief.event_start < event_starts_before)

        if event_ends_before:
            q = q.filter(
                TimedBelief.event_start
                <= pd.Timestamp(event_ends_before) - self.event_resolution
            )

        if source_types:
            q = q.filter(DataSource.type.in_(source_types))

        if exclude_source_types:
            q = q.filter(DataSource.type.not_in(exclude_source_types))

        return db.session.scalars(q).all()


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
        # get a Sensor instance attached to the database session (input sensor is detached)
        # check out Issue #683 for more details
        inspection_obj = inspect(sensor, raiseerr=False)
        if (
            inspection_obj and inspection_obj.detached
        ):  # fetch Sensor only when it is detached
            sensor = db.session.get(Sensor, sensor.id)

        tb.TimedBeliefDBMixin.__init__(self, sensor, source, **kwargs)
        tb_utils.remove_class_init_kwargs(tb.TimedBeliefDBMixin, kwargs)
        db.Model.__init__(self, **kwargs)

    @classmethod
    def search(
        cls,
        sensors: Sensor | int | str | list[Sensor | int | str],
        sensor: Sensor = None,  # deprecated
        event_starts_after: datetime_type | None = None,
        event_ends_before: datetime_type | None = None,
        beliefs_after: datetime_type | None = None,
        beliefs_before: datetime_type | None = None,
        horizons_at_least: timedelta | None = None,
        horizons_at_most: timedelta | None = None,
        source: DataSource
        | list[DataSource]
        | int
        | list[int]
        | str
        | list[str]
        | None = None,
        user_source_ids: int | list[int] | None = None,
        source_types: list[str] | None = None,
        exclude_source_types: list[str] | None = None,
        most_recent_beliefs_only: bool = True,
        most_recent_events_only: bool = False,
        most_recent_only: bool = False,
        one_deterministic_belief_per_event: bool = False,
        one_deterministic_belief_per_event_per_source: bool = False,
        resolution: str | timedelta = None,
        sum_multiple: bool = True,
    ) -> tb.BeliefsDataFrame | dict[str, tb.BeliefsDataFrame]:
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
        :param most_recent_beliefs_only: only return the most recent beliefs for each event from each source (minimum belief horizon). Defaults to True.
        :param most_recent_events_only: only return (post knowledge time) beliefs for the most recent event (maximum event start)
        :param most_recent_only: only return a single belief, the most recent from the most recent event. Fastest method if you only need one.
        :param one_deterministic_belief_per_event: only return a single value per event (no probabilistic distribution and only 1 source)
        :param one_deterministic_belief_per_event_per_source: only return a single value per event per source (no probabilistic distribution)
        :param resolution: Optional timedelta or pandas freqstr used to resample the results **
        :param sum_multiple: if True, sum over multiple sensors; otherwise, return a dictionary with sensors as key, each holding a BeliefsDataFrame as its value

        *  If user_source_ids is specified, the "user" source type is automatically included (and not excluded).
           Somewhat redundant, though still allowed, is to set both source_types and exclude_source_types.
        ** Note that:
           - timely-beliefs converts string resolutions to datetime.timedelta objects (see https://github.com/SeitaBV/timely-beliefs/issues/13).
           - for sensors recording non-instantaneous data: updates both the event frequency and the event resolution
           - for sensors recording instantaneous data: updates only the event frequency (and event resolution remains 0)
        """
        # todo: deprecate the 'sensor' argument in favor of 'sensors' (announced v0.8.0)
        sensors = tb_utils.replace_deprecated_argument(
            "sensor",
            sensor,
            "sensors",
            sensors,
        )

        # convert to list
        sensors = [sensors] if not isinstance(sensors, list) else sensors

        # convert from sensor names to sensors
        sensor_names = [s for s in sensors if isinstance(s, str)]
        if sensor_names:
            sensors = [s for s in sensors if not isinstance(s, str)]
            sensors_from_names = db.session.scalars(
                select(Sensor).filter(Sensor.name.in_(sensor_names))
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
                # Workaround (1st half) for https://github.com/FlexMeasures/flexmeasures/issues/484
                event_ends_after=event_starts_after,
                event_starts_before=event_ends_before,
                beliefs_after=beliefs_after,
                beliefs_before=beliefs_before,
                horizons_at_least=horizons_at_least,
                horizons_at_most=horizons_at_most,
                source=parsed_sources,
                most_recent_beliefs_only=most_recent_beliefs_only,
                most_recent_events_only=most_recent_events_only,
                most_recent_only=most_recent_only,
                custom_filter_criteria=source_criteria,
                custom_join_targets=custom_join_targets,
            )
            if one_deterministic_belief_per_event:
                # todo: compute median of collective belief instead of median of first belief (update expected test results accordingly)
                # todo: move to timely-beliefs: select mean/median belief
                if (
                    bdf.lineage.number_of_sources <= 1
                    and bdf.lineage.probabilistic_depth == 1
                ):
                    # Fast track, no need to loop over beliefs
                    pass
                else:
                    bdf = (
                        bdf.for_each_belief(get_median_belief)
                        .groupby(level=["event_start"], group_keys=False)
                        .apply(lambda x: x.head(1))
                    )
            elif one_deterministic_belief_per_event_per_source:
                if len(bdf) == 0 or bdf.lineage.probabilistic_depth == 1:
                    # Fast track, no need to loop over beliefs
                    pass
                else:
                    bdf = bdf.for_each_belief(get_median_belief)

            # NB resampling will be triggered if resolutions are not an exact match (also in case of str vs timedelta)
            if resolution is not None and resolution != bdf.event_resolution:
                bdf = bdf.resample_events(
                    resolution, keep_only_most_recent_belief=most_recent_beliefs_only
                )
                # Workaround (2nd half) for https://github.com/FlexMeasures/flexmeasures/issues/484
                bdf = bdf[bdf.event_starts >= event_starts_after]
                bdf = bdf[bdf.event_ends <= event_ends_before]
            bdf_dict[bdf.sensor] = bdf

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
