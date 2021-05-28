from typing import Dict, List, Tuple, Union

import isodate
import timely_beliefs as tb
from sqlalchemy.orm import Query

from flexmeasures.data.config import db
from flexmeasures.data.models.time_series import Sensor, TimedValue
from flexmeasures.utils.entity_address_utils import build_entity_address
from flexmeasures.utils.flexmeasures_inflection import humanize, pluralize


class AssetType(db.Model):
    """Describing asset types for our purposes"""

    name = db.Column(db.String(80), primary_key=True)
    # The name we want to see (don't unnecessarily capitalize, so it can be used in a sentence)
    display_name = db.Column(db.String(80), default="", unique=True)
    # The explanatory hovel label (don't unnecessarily capitalize, so it can be used in a sentence)
    hover_label = db.Column(db.String(80), nullable=True, unique=False)
    is_consumer = db.Column(db.Boolean(), nullable=False, default=False)
    is_producer = db.Column(db.Boolean(), nullable=False, default=False)
    can_curtail = db.Column(db.Boolean(), nullable=False, default=False, index=True)
    can_shift = db.Column(db.Boolean(), nullable=False, default=False, index=True)
    daily_seasonality = db.Column(db.Boolean(), nullable=False, default=False)
    weekly_seasonality = db.Column(db.Boolean(), nullable=False, default=False)
    yearly_seasonality = db.Column(db.Boolean(), nullable=False, default=False)

    def __init__(self, **kwargs):
        super(AssetType, self).__init__(**kwargs)
        self.name = self.name.replace(" ", "_").lower()
        if "display_name" not in kwargs:
            self.display_name = humanize(self.name)

    @property
    def plural_name(self) -> str:
        return pluralize(self.display_name)

    @property
    def preconditions(self) -> Dict[str, bool]:
        """Assumptions about the time series data set, such as normality and stationarity
        For now, this is usable input for Prophet (see init), but it might evolve or go away."""
        return dict(
            daily_seasonality=self.daily_seasonality,
            weekly_seasonality=self.weekly_seasonality,
            yearly_seasonality=self.yearly_seasonality,
        )

    @property
    def weather_correlations(self) -> List[str]:
        """Known correlations of weather sensor type and asset type."""
        correlations = []
        if self.name == "solar":
            correlations.append("radiation")
        if self.name == "wind":
            correlations.append("wind_speed")
        if self.name in (
            "one-way_evse",
            "two-way_evse",
            "battery",
            "building",
        ):
            correlations.append("temperature")
        return correlations

    def __repr__(self):
        return "<AssetType %r>" % self.name


class Asset(db.Model, tb.SensorDBMixin):
    """Each asset is an energy- consuming or producing hardware. """

    id = db.Column(
        db.Integer, db.ForeignKey("sensor.id"), primary_key=True, autoincrement=True
    )
    # The name
    name = db.Column(db.String(80), default="", unique=True)
    # The name we want to see (don't unnecessarily capitalize, so it can be used in a sentence)
    display_name = db.Column(db.String(80), default="", unique=True)
    # The name of the assorted AssetType
    asset_type_name = db.Column(
        db.String(80), db.ForeignKey("asset_type.name"), nullable=False
    )
    # How many MW at peak usage
    capacity_in_mw = db.Column(db.Float, nullable=False)
    # State of charge in MWh and its datetime and udi event
    min_soc_in_mwh = db.Column(db.Float, nullable=True)
    max_soc_in_mwh = db.Column(db.Float, nullable=True)
    soc_in_mwh = db.Column(db.Float, nullable=True)
    soc_datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    soc_udi_event_id = db.Column(db.Integer, nullable=True)
    # latitude is the North/South coordinate
    latitude = db.Column(db.Float, nullable=False)
    # longitude is the East/West coordinate
    longitude = db.Column(db.Float, nullable=False)
    # owner
    owner_id = db.Column(db.Integer, db.ForeignKey("fm_user.id", ondelete="CASCADE"))
    # market
    market_id = db.Column(db.Integer, db.ForeignKey("market.id"), nullable=True)

    def __init__(self, **kwargs):

        # Create a new Sensor with unique id across assets, markets and weather sensors
        if "id" not in kwargs:
            new_sensor = Sensor(name=kwargs["name"])
            db.session.add(new_sensor)
            db.session.flush()  # generates the pkey for new_sensor
            sensor_id = new_sensor.id
        else:
            # The UI may initialize Asset objects from API form data with a known id
            sensor_id = kwargs["id"]
        if "unit" not in kwargs:
            kwargs["unit"] = "MW"  # current default
        super(Asset, self).__init__(**kwargs)
        self.id = sensor_id
        if self.unit != "MW":
            raise Exception("FlexMeasures only supports MW as unit for now.")
        self.name = self.name.replace(" (MW)", "")
        if "display_name" not in kwargs:
            self.display_name = humanize(self.name)

    asset_type = db.relationship("AssetType", backref=db.backref("assets", lazy=True))
    owner = db.relationship(
        "User",
        backref=db.backref(
            "assets", lazy=True, cascade="all, delete-orphan", passive_deletes=True
        ),
    )
    market = db.relationship("Market", backref=db.backref("assets", lazy=True))

    @property
    def power_unit(self) -> float:
        """Return the 'unit' property of the generic asset, just with a more insightful name."""
        return self.unit

    @property
    def entity_address_fm0(self) -> str:
        """Entity address under the fm0 scheme for entity addresses."""
        return build_entity_address(
            dict(owner_id=self.owner_id, asset_id=self.id),
            "connection",
            fm_scheme="fm0",
        )

    @property
    def entity_address(self) -> str:
        """Entity address under the latest fm scheme for entity addresses."""
        return build_entity_address(dict(sensor_id=self.id), "sensor")

    @property
    def location(self) -> Tuple[float, float]:
        return self.latitude, self.longitude

    def capacity_factor_in_percent_for(self, load_in_mw) -> int:
        if self.capacity_in_mw == 0:
            return 0
        return min(round((load_in_mw / self.capacity_in_mw) * 100, 2), 100)

    @property
    def is_pure_consumer(self) -> bool:
        """Return True if this asset is consuming but not producing."""
        return self.asset_type.is_consumer and not self.asset_type.is_producer

    @property
    def is_pure_producer(self) -> bool:
        """Return True if this asset is producing but not consuming."""
        return self.asset_type.is_producer and not self.asset_type.is_consumer

    def to_dict(self) -> Dict[str, Union[str, float]]:
        return dict(
            name=self.name,
            display_name=self.display_name,
            asset_type_name=self.asset_type_name,
            latitude=self.latitude,
            longitude=self.longitude,
            capacity_in_mw=self.capacity_in_mw,
        )

    def __repr__(self):
        return "<Asset %s:%r (%s), res.: %s on market %s>" % (
            self.id,
            self.name,
            self.asset_type_name,
            self.event_resolution,
            self.market,
        )


def assets_share_location(assets: List[Asset]) -> bool:
    """
    Return True if all assets in this list are located on the same spot.
    TODO: In the future, we might soften this to compare if assets are in the same "housing" or "site".
    """
    if not assets:
        return True
    return all([a.location == assets[0].location for a in assets])


class Power(TimedValue, db.Model):
    """
    All measurements of power data are stored in one slim table.
    Negative values indicate consumption.
    TODO: datetime objects take up most of the space (12 bytes each)). One way out is to normalise them out to a table.
    TODO: If there are more than one measurement per asset per time step possible, we can expand rather easily.
    """

    asset_id = db.Column(
        db.Integer(),
        db.ForeignKey("asset.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    asset = db.relationship(
        "Asset",
        backref=db.backref(
            "measurements",
            lazy=True,
            cascade="all, delete-orphan",
            passive_deletes=True,
        ),
    )

    @classmethod
    def make_query(
        cls,
        **kwargs,
    ) -> Query:
        """Construct the database query."""
        return super().make_query(asset_class=Asset, **kwargs)

    def to_dict(self):
        return {
            "datetime": isodate.datetime_isoformat(self.datetime),
            "asset_id": self.asset_id,
            "value": self.value,
            "horizon": self.horizon,
        }

    def __init__(self, **kwargs):
        super(Power, self).__init__(**kwargs)

    def __repr__(self):
        return "<Power %.5f on Asset %s at %s by DataSource %s, horizon %s>" % (
            self.value,
            self.asset_id,
            self.datetime,
            self.data_source_id,
            self.horizon,
        )
