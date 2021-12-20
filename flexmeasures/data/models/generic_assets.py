from typing import Optional, Tuple

from sqlalchemy.ext.hybrid import hybrid_method
from sqlalchemy.sql.expression import func

from sqlalchemy.ext.mutable import MutableDict

from flexmeasures.data import db
from flexmeasures.utils import geo_utils


class GenericAssetType(db.Model):
    """An asset type defines what type an asset belongs to.

    Examples of asset types: WeatherStation, Market, CP, EVSE, WindTurbine, SolarPanel, Building.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="")
    description = db.Column(db.String(80), nullable=True, unique=False)


class GenericAsset(db.Model):
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

    def get_attribute(self, attribute: str):
        if attribute in self.attributes:
            return self.attributes[attribute]

    def has_attribute(self, attribute: str) -> bool:
        return attribute in self.attributes

    def set_attribute(self, attribute: str, value):
        if self.has_attribute(attribute):
            self.attributes[attribute] = value


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
