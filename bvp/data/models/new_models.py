from typing import Tuple

from bvp.data.config import db
import timely_beliefs as tb


class Sensor(db.Model, tb.SensorDBMixin):
    """A sensor defines common properties of measured events.

    Examples of common event properties:
    - the event resolution: how long an event lasts, where timedelta(0) denotes an instantaneous state
    - the knowledge horizon: how long before (an event starts) the event could be known
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="")
    latitude = db.Column(
        db.Float, nullable=False
    )  # North/South coordinate; if null, check .asset.latitude
    longitude = db.Column(
        db.Float, nullable=False
    )  # East/West coordinate; if null, check .asset.longitude

    sensor_type_id = db.Column(
        db.String(80), db.ForeignKey("sensor_type.id"), nullable=False
    )
    sensor_type = db.relationship(
        "SensorType", backref=db.backref("sensors", lazy=True)
    )

    asset_id = db.Column(db.Integer, db.ForeignKey("asset.id"), nullable=False)
    asset = db.relationship("Asset", backref=db.backref("sensors", lazy=True))

    @property
    def location(self) -> Tuple[float, float]:
        if not (self.latitude and self.longitude):
            return self.asset.latitude, self.asset.longitude
        return self.latitude, self.longitude

    @property
    def unit(self) -> str:
        return self.sensor_type.unit


class SensorType(db.Model):
    """A sensor type defines what type of data a sensor measures, and includes a unit.

    Examples of physical sensor types: temperature, wind speed, wind direction, a barometer.
    Examples of economic sensor types: unit price, gross domestic product, cVaR.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="")
    unit = db.Column(db.String(80), nullable=False)
    hover_label = db.Column(db.String(80), nullable=True, unique=False)


class Asset(db.Model):
    """An asset is something that has economic value.

    Examples of tangible assets: a house, a ship, a weather station.
    Examples of intangible assets: a market, a country, a copyright.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="")
    latitude = db.Column(db.Float, nullable=True)  # if null, asset is virtual
    longitude = db.Column(db.Float, nullable=True)  # if null, asset is virtual

    asset_type_id = db.Column(
        db.String(80), db.ForeignKey("asset_type.id"), nullable=False
    )
    asset_type = db.relationship("AssetType", backref=db.backref("assets", lazy=True))

    owner_id = db.Column(
        db.Integer, db.ForeignKey("bvp_users.id", ondelete="CASCADE"), nullable=True
    )  # null means public asset
    owner = db.relationship(
        "User",
        backref=db.backref(
            "assets", lazy=True, cascade="all, delete-orphan", passive_deletes=True
        ),
    )

    @property
    def location(self) -> Tuple[float, float]:
        return self.latitude, self.longitude


class AssetType(db.Model):
    """An asset type defines what type an asset belongs to.

    Examples of asset types: WeatherStation, Market, CP, EVSE, WindTurbine, SolarPanel, Building.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="")
    hover_label = db.Column(db.String(80), nullable=True, unique=False)


class SensorRelationship(db.Model):
    """A sensor relationship defines dependency or constraint relationships between sensors.

    sensor1 depends on sensor2 or is constrained by sensor2.
    """

    id = db.Column(db.Integer, primary_key=True)
    relationship = db.Column(
        db.Enum(
            "is_sum_of",
            "is_equal_or_less_than",
            "is",
            "is_equal_or_greater_than",
            "is_product_of",
            "is_less_than",
            "is_greater_than",
            "is_regressed_by",
        ),
        nullable=False,
    )

    sensor1_id = db.Column(db.Integer, db.ForeignKey("sensor.id"), nullable=False)
    sensor1 = db.relationship(
        "Sensor",
        foreign_keys=[sensor1_id],
        backref=db.backref("dependent_related_sensors", lazy=True),
    )

    sensor2_id = db.Column(db.Integer, db.ForeignKey("sensor.id"), nullable=False)
    sensor2 = db.relationship(
        "Sensor",
        foreign_keys=[sensor2_id],
        backref=db.backref("independent_related_sensors", lazy=True),
    )

    @property
    def relationship_type(self) -> str:
        if self.relationship in (
            "is",
            "is_less_than",
            "is_greater_than",
            "is_equal_or_less_than",
            "is_equal_or_greater_than",
        ):
            return "constraint"
        return "dependency"


class AssetGrouping(db.Model):
    """An asset grouping defines grouping relationships between assets.

    asset1 combines a group of assets.
    asset2 belongs to that group.
    """

    id = db.Column(db.Integer, primary_key=True)

    asset1_id = db.Column(db.Integer, db.ForeignKey("asset.id"), nullable=False)
    asset1 = db.relationship(
        "Asset",
        foreign_keys=[asset1_id],
        backref=db.backref("combines_assets", lazy=True),
    )

    asset2_id = db.Column(db.Integer, db.ForeignKey("asset.id"), nullable=False)
    asset2 = db.relationship(
        "Asset",
        foreign_keys=[asset2_id],
        backref=db.backref("belongs_to_assets", lazy=True),
    )
