from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple, List, Union
import json

from flask_security import current_user
import pandas as pd
from sqlalchemy.engine import Row
from sqlalchemy.ext.hybrid import hybrid_method
from sqlalchemy.sql.expression import func
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.schema import UniqueConstraint
from timely_beliefs import BeliefsDataFrame, utils as tb_utils

from flexmeasures.data import db
from flexmeasures.data.models.annotations import Annotation, to_annotation_frame
from flexmeasures.data.models.charts import chart_type_to_chart_specs
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.parsing_utils import parse_source_arg
from flexmeasures.data.models.user import User
from flexmeasures.data.queries.annotations import query_asset_annotations
from flexmeasures.auth.policy import AuthModelMixin, EVERY_LOGGED_IN_USER
from flexmeasures.utils import geo_utils
from flexmeasures.utils.time_utils import server_now


class GenericAssetType(db.Model):
    """An asset type defines what type an asset belongs to.

    Examples of asset types: WeatherStation, Market, CP, EVSE, WindTurbine, SolarPanel, Building.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="", unique=True)
    description = db.Column(db.String(80), nullable=True, unique=False)


class GenericAsset(db.Model, AuthModelMixin):
    """An asset is something that has economic value.

    Examples of tangible assets: a house, a ship, a weather station.
    Examples of intangible assets: a market, a country, a copyright.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="")
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    attributes = db.Column(MutableDict.as_mutable(db.JSON), nullable=False, default={})

    generic_asset_type_id = db.Column(
        db.Integer, db.ForeignKey("generic_asset_type.id"), nullable=False
    )
    generic_asset_type = db.relationship(
        "GenericAssetType",
        foreign_keys=[generic_asset_type_id],
        backref=db.backref("generic_assets", lazy=True),
    )
    annotations = db.relationship(
        "Annotation",
        secondary="annotations_assets",
        backref=db.backref("assets", lazy="dynamic"),
    )

    __table_args__ = (
        UniqueConstraint(
            "name",
            "account_id",
            name="generic_asset_name_account_id_key",
        ),
    )

    def __acl__(self):
        """
        All logged-in users can read if the asset is public.
        Within same account, everyone can create, read and update.
        Deletion is left to account admins.
        """
        return {
            "create-children": f"account:{self.account_id}",
            "read": f"account:{self.account_id}"
            if self.account_id is not None
            else EVERY_LOGGED_IN_USER,
            "update": f"account:{self.account_id}",
            "delete": (f"account:{self.account_id}", "role:account-admin"),
        }

    def __repr__(self):
        return "<GenericAsset %s: %r (%s)>" % (
            self.id,
            self.name,
            self.generic_asset_type.name,
        )

    @property
    def asset_type(self) -> GenericAssetType:
        """This property prepares for dropping the "generic" prefix later"""
        return self.generic_asset_type

    account_id = db.Column(
        db.Integer, db.ForeignKey("account.id", ondelete="CASCADE"), nullable=True
    )  # if null, asset is public

    owner = db.relationship(
        "Account",
        backref=db.backref(
            "generic_assets",
            foreign_keys=[account_id],
            lazy=True,
            cascade="all, delete-orphan",
            passive_deletes=True,
        ),
    )

    @property
    def location(self) -> Optional[Tuple[float, float]]:
        location = (self.latitude, self.longitude)
        if None not in location:
            return location

    @hybrid_method
    def great_circle_distance(self, **kwargs):
        """Query great circle distance (in km).

        Can be called with an object that has latitude and longitude properties, for example:

            great_circle_distance(object=asset)

        Can also be called with latitude and longitude parameters, for example:

            great_circle_distance(latitude=32, longitude=54)
            great_circle_distance(lat=32, lng=54)

        """
        other_location = geo_utils.parse_lat_lng(kwargs)
        if None in other_location:
            return None
        return geo_utils.earth_distance(self.location, other_location)

    @great_circle_distance.expression
    def great_circle_distance(self, **kwargs):
        """Query great circle distance (unclear if in km or in miles).

        Can be called with an object that has latitude and longitude properties, for example:

            great_circle_distance(object=asset)

        Can also be called with latitude and longitude parameters, for example:

            great_circle_distance(latitude=32, longitude=54)
            great_circle_distance(lat=32, lng=54)

        Requires the following Postgres extensions: earthdistance and cube.
        """
        other_location = geo_utils.parse_lat_lng(kwargs)
        if None in other_location:
            return None
        return func.earth_distance(
            func.ll_to_earth(self.latitude, self.longitude),
            func.ll_to_earth(*other_location),
        )

    def get_attribute(self, attribute: str, default: Any = None):
        if attribute in self.attributes:
            return self.attributes[attribute]
        return default

    def has_attribute(self, attribute: str) -> bool:
        return attribute in self.attributes

    def set_attribute(self, attribute: str, value):
        if self.has_attribute(attribute):
            self.attributes[attribute] = value

    @property
    def has_power_sensors(self) -> bool:
        """True if at least one power sensor is attached"""
        return any([s.measures_power for s in self.sensors])

    @property
    def has_energy_sensors(self) -> bool:
        """True if at least one energy sensor is attached"""
        return any([s.measures_energy for s in self.sensors])

    def add_annotations(
        self,
        df: pd.DataFrame,
        annotation_type: str,
        commit_transaction: bool = False,
    ):
        """Add a data frame describing annotations to the database, and assign the annotations to this asset."""
        annotations = Annotation.add(df, annotation_type=annotation_type)
        self.annotations += annotations
        db.session.add(self)
        if commit_transaction:
            db.session.commit()

    def search_annotations(
        self,
        annotations_after: Optional[datetime] = None,
        annotations_before: Optional[datetime] = None,
        source: Optional[
            Union[DataSource, List[DataSource], int, List[int], str, List[str]]
        ] = None,
        annotation_type: str = None,
        include_account_annotations: bool = False,
        as_frame: bool = False,
    ) -> Union[List[Annotation], pd.DataFrame]:
        """Return annotations assigned to this asset, and optionally, also those assigned to the asset's account.

        :param annotations_after: only return annotations that end after this datetime (exclusive)
        :param annotations_before: only return annotations that start before this datetime (exclusive)
        """
        parsed_sources = parse_source_arg(source)
        annotations = query_asset_annotations(
            asset_id=self.id,
            annotations_after=annotations_after,
            annotations_before=annotations_before,
            sources=parsed_sources,
            annotation_type=annotation_type,
        ).all()
        if include_account_annotations:
            annotations += self.owner.search_annotations(
                annotations_after=annotations_after,
                annotations_before=annotations_before,
                source=source,
            )

        return to_annotation_frame(annotations) if as_frame else annotations

    def count_annotations(
        self,
        annotation_starts_after: Optional[datetime] = None,  # deprecated
        annotations_after: Optional[datetime] = None,
        annotation_ends_before: Optional[datetime] = None,  # deprecated
        annotations_before: Optional[datetime] = None,
        source: Optional[
            Union[DataSource, List[DataSource], int, List[int], str, List[str]]
        ] = None,
        annotation_type: str = None,
    ) -> int:
        """Count the number of annotations assigned to this asset."""

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
        return query_asset_annotations(
            asset_id=self.id,
            annotations_after=annotations_after,
            annotations_before=annotations_before,
            sources=parsed_sources,
            annotation_type=annotation_type,
        ).count()

    def chart(
        self,
        chart_type: str = "chart_for_multiple_sensors",
        event_starts_after: Optional[datetime] = None,
        event_ends_before: Optional[datetime] = None,
        beliefs_after: Optional[datetime] = None,
        beliefs_before: Optional[datetime] = None,
        source: Optional[
            Union[DataSource, List[DataSource], int, List[int], str, List[str]]
        ] = None,
        include_data: bool = False,
        dataset_name: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Create a vega-lite chart showing sensor data.

        :param chart_type: currently only "bar_chart" # todo: where can we properly list the available chart types?
        :param event_starts_after: only return beliefs about events that start after this datetime (inclusive)
        :param event_ends_before: only return beliefs about events that end before this datetime (inclusive)
        :param beliefs_after: only return beliefs formed after this datetime (inclusive)
        :param beliefs_before: only return beliefs formed before this datetime (inclusive)
        :param source: search only beliefs by this source (pass the DataSource, or its name or id) or list of sources
        :param include_data: if True, include data in the chart, or if False, exclude data
        :param dataset_name: optionally name the dataset used in the chart (the default name is sensor_<id>)
        :returns: JSON string defining vega-lite chart specs
        """
        sensors = self.sensors_to_show
        for sensor in sensors:
            sensor.sensor_type = sensor.get_attribute("sensor_type", sensor.name)

        # Set up chart specification
        if dataset_name is None:
            dataset_name = "asset_" + str(self.id)
        if event_starts_after:
            kwargs["event_starts_after"] = event_starts_after
        if event_ends_before:
            kwargs["event_ends_before"] = event_ends_before
        chart_specs = chart_type_to_chart_specs(
            chart_type,
            sensors=sensors,
            dataset_name=dataset_name,
            **kwargs,
        )

        if include_data:
            # Get data
            data = self.search_beliefs(
                sensors=sensors,
                as_json=True,
                event_starts_after=event_starts_after,
                event_ends_before=event_ends_before,
                beliefs_after=beliefs_after,
                beliefs_before=beliefs_before,
                source=source,
            )

            # Combine chart specs and data
            chart_specs["datasets"] = {
                dataset_name: json.loads(data),
            }

        return chart_specs

    def search_beliefs(
        self,
        sensors: Optional[List["Sensor"]] = None,  # noqa F821
        event_starts_after: Optional[datetime] = None,
        event_ends_before: Optional[datetime] = None,
        beliefs_after: Optional[datetime] = None,
        beliefs_before: Optional[datetime] = None,
        horizons_at_least: Optional[timedelta] = None,
        horizons_at_most: Optional[timedelta] = None,
        source: Optional[
            Union[DataSource, List[DataSource], int, List[int], str, List[str]]
        ] = None,
        most_recent_events_only: bool = False,
        as_json: bool = False,
    ) -> Union[BeliefsDataFrame, str]:
        """Search all beliefs about events for all sensors of this asset

        If you don't set any filters, you get the most recent beliefs about all events.

        :param sensors: only return beliefs about events registered by these sensors
        :param event_starts_after: only return beliefs about events that start after this datetime (inclusive)
        :param event_ends_before: only return beliefs about events that end before this datetime (inclusive)
        :param beliefs_after: only return beliefs formed after this datetime (inclusive)
        :param beliefs_before: only return beliefs formed before this datetime (inclusive)
        :param horizons_at_least: only return beliefs with a belief horizon equal or greater than this timedelta (for example, use timedelta(0) to get ante knowledge time beliefs)
        :param horizons_at_most: only return beliefs with a belief horizon equal or less than this timedelta (for example, use timedelta(0) to get post knowledge time beliefs)
        :param source: search only beliefs by this source (pass the DataSource, or its name or id) or list of sources
        :param most_recent_events_only: only return (post knowledge time) beliefs for the most recent event (maximum event start)
        :param as_json: return beliefs in JSON format (e.g. for use in charts) rather than as BeliefsDataFrame
        :returns: dictionary of BeliefsDataFrames or JSON string (if as_json is True)
        """
        bdf_dict = {}
        if sensors is None:
            sensors = self.sensors
        for sensor in sensors:
            bdf_dict[sensor] = sensor.search_beliefs(
                event_starts_after=event_starts_after,
                event_ends_before=event_ends_before,
                beliefs_after=beliefs_after,
                beliefs_before=beliefs_before,
                horizons_at_least=horizons_at_least,
                horizons_at_most=horizons_at_most,
                source=source,
                most_recent_beliefs_only=True,
                most_recent_events_only=most_recent_events_only,
                one_deterministic_belief_per_event_per_source=True,
            )
        if as_json:
            from flexmeasures.data.services.time_series import simplify_index

            if sensors:
                condition = list(
                    bdf.event_resolution
                    for bdf in bdf_dict.values()
                    if bdf.event_resolution > timedelta(0)
                )
                minimum_non_zero_resolution = (
                    min(condition) if any(condition) else timedelta(0)
                )
                df_dict = {}
                for sensor, bdf in bdf_dict.items():
                    if bdf.event_resolution > timedelta(0):
                        bdf = bdf.resample_events(minimum_non_zero_resolution)
                    df = simplify_index(
                        bdf, index_levels_to_columns=["source"]
                    ).set_index(["source"], append=True)
                    df_dict[sensor.id] = df.rename(columns=dict(event_value=sensor.id))
                df = list(df_dict.values())[0].join(
                    list(df_dict.values())[1:], how="outer"
                )
            else:
                df = simplify_index(
                    BeliefsDataFrame(), index_levels_to_columns=["source"]
                ).set_index(["source"], append=True)
            df = df.reset_index()
            df["source"] = df["source"].apply(lambda x: x.to_dict())
            return df.to_json(orient="records")
        return bdf_dict

    @property
    def sensors_to_show(self) -> List["Sensor"]:  # noqa F821
        """Sensors to show, as defined by the sensors_to_show attribute.

        Defaults to two of the asset's sensors.
        """
        if not self.has_attribute("sensors_to_show"):
            return self.sensors[:2]

        from flexmeasures.data.services.sensors import get_public_sensors

        sensor_ids = self.get_attribute("sensors_to_show")
        sensor_map = {
            sensor.id: sensor
            for sensor in self.sensors + get_public_sensors(sensor_ids)
            if sensor.id in sensor_ids
        }

        # Return sensors in the order given by the sensors_to_show attribute
        return [sensor_map[sensor_id] for sensor_id in sensor_ids]

    @property
    def timezone(
        self,
    ) -> str:
        """Timezone relevant to the asset.

        If a timezone is not given as an attribute of the asset, it is taken from one of its sensors.
        """
        if self.has_attribute("timezone"):
            return self.get_attribute("timezone")
        if self.sensors:
            return self.sensors[0].timezone
        return "UTC"

    @property
    def timerange(self) -> Dict[str, datetime]:
        """Time range for which sensor data exists.

        :returns: dictionary with start and end, for example:
                  {
                      'start': datetime.datetime(2020, 12, 3, 14, 0, tzinfo=pytz.utc),
                      'end': datetime.datetime(2020, 12, 3, 14, 30, tzinfo=pytz.utc)
                  }
        """
        return self.get_timerange(self.sensors)

    @property
    def timerange_of_sensors_to_show(self) -> Dict[str, datetime]:
        """Time range for which sensor data exists, for sensors to show.

        :returns: dictionary with start and end, for example:
                  {
                      'start': datetime.datetime(2020, 12, 3, 14, 0, tzinfo=pytz.utc),
                      'end': datetime.datetime(2020, 12, 3, 14, 30, tzinfo=pytz.utc)
                  }
        """
        return self.get_timerange(self.sensors_to_show)

    @classmethod
    def get_timerange(cls, sensors: List["Sensor"]) -> Dict[str, datetime]:  # noqa F821
        """Time range for which sensor data exists.

        :param sensors: sensors to check
        :returns: dictionary with start and end, for example:
                  {
                      'start': datetime.datetime(2020, 12, 3, 14, 0, tzinfo=pytz.utc),
                      'end': datetime.datetime(2020, 12, 3, 14, 30, tzinfo=pytz.utc)
                  }
        """
        from flexmeasures.data.models.time_series import TimedBelief

        sensor_ids = [sensor.id for sensor in sensors]
        least_recent_query = (
            TimedBelief.query.filter(TimedBelief.sensor_id.in_(sensor_ids))
            .order_by(TimedBelief.event_start.asc())
            .limit(1)
        )
        most_recent_query = (
            TimedBelief.query.filter(TimedBelief.sensor_id.in_(sensor_ids))
            .order_by(TimedBelief.event_start.desc())
            .limit(1)
        )
        results = least_recent_query.union_all(most_recent_query).all()
        if not results:
            # return now in case there is no data for any of the sensors
            now = server_now()
            return dict(start=now, end=now)
        least_recent, most_recent = results
        return dict(start=least_recent.event_start, end=most_recent.event_end)


def create_generic_asset(generic_asset_type: str, **kwargs) -> GenericAsset:
    """Create a GenericAsset and assigns it an id.

    :param generic_asset_type: "asset", "market" or "weather_sensor"
    :param kwargs:              should have values for keys "name", and:
                                - "asset_type_name" or "asset_type" when generic_asset_type is "asset"
                                - "market_type_name" or "market_type" when generic_asset_type is "market"
                                - "weather_sensor_type_name" or "weather_sensor_type" when generic_asset_type is "weather_sensor"
                                - alternatively, "sensor_type" is also fine
    :returns:                   the created GenericAsset
    """
    asset_type_name = kwargs.pop(f"{generic_asset_type}_type_name", None)
    if asset_type_name is None:
        if f"{generic_asset_type}_type" in kwargs:
            asset_type_name = kwargs.pop(f"{generic_asset_type}_type").name
        else:
            asset_type_name = kwargs.pop("sensor_type").name
    generic_asset_type = GenericAssetType.query.filter_by(
        name=asset_type_name
    ).one_or_none()
    if generic_asset_type is None:
        raise ValueError(f"Cannot find GenericAssetType {asset_type_name} in database.")
    new_generic_asset = GenericAsset(
        name=kwargs["name"],
        generic_asset_type_id=generic_asset_type.id,
        attributes=kwargs["attributes"] if "attributes" in kwargs else {},
    )
    for arg in ("latitude", "longitude", "account_id"):
        if arg in kwargs:
            setattr(new_generic_asset, arg, kwargs[arg])
    db.session.add(new_generic_asset)
    db.session.flush()  # generates the pkey for new_generic_asset
    return new_generic_asset


def assets_share_location(assets: List[GenericAsset]) -> bool:
    """
    Return True if all assets in this list are located on the same spot.
    TODO: In the future, we might soften this to compare if assets are in the same "housing" or "site".
    """
    if not assets:
        return True
    return all([a.location == assets[0].location for a in assets])


def get_center_location_of_assets(user: Optional[User]) -> Tuple[float, float]:
    """
    Find the center position between all generic assets of the user's account.
    """
    query = (
        "Select (min(latitude) + max(latitude)) / 2 as latitude,"
        " (min(longitude) + max(longitude)) / 2 as longitude"
        " from generic_asset"
    )
    if user is None:
        user = current_user
    query += f" where generic_asset.account_id = {user.account_id}"
    locations: List[Row] = db.session.execute(query + ";").fetchall()
    if (
        len(locations) == 0
        or locations[0].latitude is None
        or locations[0].longitude is None
    ):
        return 52.366, 4.904  # Amsterdam, NL
    return locations[0].latitude, locations[0].longitude
