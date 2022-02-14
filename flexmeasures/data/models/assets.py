from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union

import isodate
import timely_beliefs as tb
import timely_beliefs.utils as tb_utils
from sqlalchemy.orm import Query

from flexmeasures.data import db
from flexmeasures.data.models.legacy_migration_utils import (
    copy_old_sensor_attributes,
    get_old_model_type,
)
from flexmeasures.data.models.user import User
from flexmeasures.data.models.time_series import Sensor, TimedValue, TimedBelief
from flexmeasures.data.models.generic_assets import (
    create_generic_asset,
    GenericAsset,
    GenericAssetType,
)
from flexmeasures.utils.entity_address_utils import build_entity_address
from flexmeasures.utils.flexmeasures_inflection import humanize, pluralize


class AssetType(db.Model):
    """
    Describing asset types for our purposes

    This model is now considered legacy. See GenericAssetType.
    """

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
        generic_asset_type = GenericAssetType.query.filter_by(
            name=kwargs["name"]
        ).one_or_none()
        if not generic_asset_type:
            generic_asset_type = GenericAssetType(
                name=kwargs["name"], description=kwargs.get("hover_label", None)
            )
            db.session.add(generic_asset_type)
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
    """
    Each asset is an energy- consuming or producing hardware.

    This model is now considered legacy. See GenericAsset and Sensor.
    """

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

        if "unit" not in kwargs:
            kwargs["unit"] = "MW"  # current default
        super(Asset, self).__init__(**kwargs)

        # Create a new Sensor with unique id across assets, markets and weather sensors
        # Also keep track of ownership by creating a GenericAsset and assigning the new Sensor to it.
        if "id" not in kwargs:

            asset_type = get_old_model_type(
                kwargs, AssetType, "asset_type_name", "asset_type"
            )

            # Set up generic asset
            generic_asset_kwargs = {
                **kwargs,
                **copy_old_sensor_attributes(
                    self,
                    old_sensor_type_attributes=[
                        "can_curtail",
                        "can_shift",
                    ],
                    old_sensor_attributes=[
                        "display_name",
                        "min_soc_in_mwh",
                        "max_soc_in_mwh",
                        "soc_in_mwh",
                        "soc_datetime",
                        "soc_udi_event_id",
                    ],
                    old_sensor_type=asset_type,
                ),
            }

            if "owner_id" in kwargs:
                owner = User.query.get(kwargs["owner_id"])
                if owner:
                    generic_asset_kwargs.update(account_id=owner.account_id)
            new_generic_asset = create_generic_asset("asset", **generic_asset_kwargs)

            # Set up sensor
            new_sensor = Sensor(
                name=kwargs["name"],
                generic_asset=new_generic_asset,
                **copy_old_sensor_attributes(
                    self,
                    old_sensor_type_attributes=[
                        "is_consumer",
                        "is_producer",
                        "daily_seasonality",
                        "weekly_seasonality",
                        "yearly_seasonality",
                        "weather_correlations",
                    ],
                    old_sensor_attributes=[
                        "display_name",
                        "capacity_in_mw",
                        "market_id",
                    ],
                    old_sensor_type=asset_type,
                ),
            )
            db.session.add(new_sensor)
            db.session.flush()  # generates the pkey for new_sensor
            sensor_id = new_sensor.id
        else:
            # The UI may initialize Asset objects from API form data with a known id
            sensor_id = kwargs["id"]
        self.id = sensor_id
        if self.unit != "MW":
            raise Exception("FlexMeasures only supports MW as unit for now.")
        self.name = self.name.replace(" (MW)", "")
        if "display_name" not in kwargs:
            self.display_name = humanize(self.name)

        # Copy over additional columns from (newly created) Asset to (newly created) Sensor
        if "id" not in kwargs:
            db.session.add(self)
            db.session.flush()  # make sure to generate each column for the old sensor
            new_sensor.unit = self.unit
            new_sensor.event_resolution = self.event_resolution
            new_sensor.knowledge_horizon_fnc = self.knowledge_horizon_fnc
            new_sensor.knowledge_horizon_par = self.knowledge_horizon_par

    asset_type = db.relationship("AssetType", backref=db.backref("assets", lazy=True))
    owner = db.relationship(
        "User",
        backref=db.backref(
            "assets", lazy=True, cascade="all, delete-orphan", passive_deletes=True
        ),
    )
    market = db.relationship("Market", backref=db.backref("assets", lazy=True))

    def latest_state(self, event_ends_before: Optional[datetime] = None) -> "Power":
        """Search the most recent event for this sensor, optionally before some datetime."""
        # todo: replace with Sensor.latest_state
        power_query = (
            Power.query.filter(Power.sensor_id == self.id)
            .filter(Power.horizon <= timedelta(hours=0))
            .order_by(Power.datetime.desc())
        )
        if event_ends_before is not None:
            power_query = power_query.filter(
                Power.datetime + self.event_resolution <= event_ends_before
            )
        return power_query.first()

    @property
    def corresponding_sensor(self) -> Sensor:
        return db.session.query(Sensor).get(self.id)

    @property
    def generic_asset(self) -> GenericAsset:
        return db.session.query(GenericAsset).get(self.corresponding_sensor.id)

    def get_attribute(self, attribute: str):
        """Looks for the attribute on the corresponding Sensor.

        This should be used by all code to read these attributes,
        over accessing them directly on this class,
        as this table is in the process to be replaced by the Sensor table.
        """
        return self.corresponding_sensor.get_attribute(attribute)

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

    This model is now considered legacy. See TimedBelief.
    """

    sensor_id = db.Column(
        db.Integer(),
        db.ForeignKey("sensor.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    sensor = db.relationship(
        "Sensor",
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
        return super().make_query(**kwargs)

    def to_dict(self):
        return {
            "datetime": isodate.datetime_isoformat(self.datetime),
            "sensor_id": self.sensor_id,
            "value": self.value,
            "horizon": self.horizon,
        }

    def __init__(self, use_legacy_kwargs: bool = True, **kwargs):
        # todo: deprecate the 'asset_id' argument in favor of 'sensor_id' (announced v0.8.0)
        if "asset_id" in kwargs and "sensor_id" not in kwargs:
            kwargs["sensor_id"] = tb_utils.replace_deprecated_argument(
                "asset_id",
                kwargs["asset_id"],
                "sensor_id",
                None,
            )
            kwargs.pop("asset_id", None)

        # todo: deprecate the 'Power' class in favor of 'TimedBelief' (announced v0.8.0)
        if use_legacy_kwargs is False:
            # Create corresponding TimedBelief
            belief = TimedBelief(**kwargs)
            db.session.add(belief)

            # Convert key names for legacy model
            kwargs["value"] = kwargs.pop("event_value")
            kwargs["datetime"] = kwargs.pop("event_start")
            kwargs["horizon"] = kwargs.pop("belief_horizon")
            kwargs["sensor_id"] = kwargs.pop("sensor").id
            kwargs["data_source_id"] = kwargs.pop("source").id

        else:
            import warnings

            warnings.warn(
                f"The {self.__class__} class is deprecated. Switch to using the TimedBelief class to suppress this warning.",
                FutureWarning,
            )

        super(Power, self).__init__(**kwargs)

    def __repr__(self):
        return "<Power %.5f on Sensor %s at %s by DataSource %s, horizon %s>" % (
            self.value,
            self.sensor_id,
            self.datetime,
            self.data_source_id,
            self.horizon,
        )
