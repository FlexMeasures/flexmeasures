from datetime import datetime
from typing import Optional, Tuple, List, Union

from flask_security import current_user
import pandas as pd
from sqlalchemy.engine import Row
from sqlalchemy.ext.hybrid import hybrid_method
from sqlalchemy.sql.expression import func
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.schema import UniqueConstraint
from timely_beliefs import utils as tb_utils

from flexmeasures.data import db
from flexmeasures.data.models.annotations import Annotation, to_annotation_frame
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.parsing_utils import parse_source_arg
from flexmeasures.data.models.user import User
from flexmeasures.data.queries.annotations import query_asset_annotations
from flexmeasures.auth.policy import AuthModelMixin, EVERY_LOGGED_IN_USER
from flexmeasures.utils import geo_utils


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
    account = db.relationship("Account", backref=db.backref("assets", lazy=True))

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

    def get_attribute(self, attribute: str):
        if attribute in self.attributes:
            return self.attributes[attribute]

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
