from typing import Dict

import timely_beliefs as tb
from timely_beliefs.sensors.func_store import knowledge_horizons
import timely_beliefs.utils as tb_utils
from sqlalchemy.orm import Query

from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import (
    create_generic_asset,
    GenericAsset,
    GenericAssetType,
)
from flexmeasures.data.models.legacy_migration_utils import (
    copy_old_sensor_attributes,
    get_old_model_type,
)
from flexmeasures.data.models.time_series import Sensor, TimedValue, TimedBelief
from flexmeasures.utils.entity_address_utils import build_entity_address
from flexmeasures.utils.flexmeasures_inflection import humanize


class MarketType(db.Model):
    """
    Describing market types for our purposes.
    This model is now considered legacy. See GenericAssetType.
    """

    name = db.Column(db.String(80), primary_key=True)
    display_name = db.Column(db.String(80), default="", unique=True)

    daily_seasonality = db.Column(db.Boolean(), nullable=False, default=False)
    weekly_seasonality = db.Column(db.Boolean(), nullable=False, default=False)
    yearly_seasonality = db.Column(db.Boolean(), nullable=False, default=False)

    def __init__(self, **kwargs):
        kwargs["name"] = kwargs["name"].replace(" ", "_").lower()
        if "display_name" not in kwargs:
            kwargs["display_name"] = humanize(kwargs["name"])

        super(MarketType, self).__init__(**kwargs)

        generic_asset_type = GenericAssetType(
            name=kwargs["name"], description=kwargs.get("hover_label", None)
        )
        db.session.add(generic_asset_type)

    @property
    def preconditions(self) -> Dict[str, bool]:
        """Assumptions about the time series data set, such as normality and stationarity
        For now, this is usable input for Prophet (see init), but it might evolve or go away."""
        return dict(
            daily_seasonality=self.daily_seasonality,
            weekly_seasonality=self.weekly_seasonality,
            yearly_seasonality=self.yearly_seasonality,
        )

    def __repr__(self):
        return "<MarketType %r>" % self.name


class Market(db.Model, tb.SensorDBMixin):
    """
    Each market is a pricing service.

    This model is now considered legacy. See GenericAsset and Sensor.
    """

    id = db.Column(
        db.Integer, db.ForeignKey("sensor.id"), primary_key=True, autoincrement=True
    )
    name = db.Column(db.String(80), unique=True)
    display_name = db.Column(db.String(80), default="", unique=True)
    market_type_name = db.Column(
        db.String(80), db.ForeignKey("market_type.name"), nullable=False
    )

    def __init__(self, **kwargs):
        # Set default knowledge horizon function for an economic sensor
        if "knowledge_horizon_fnc" not in kwargs:
            kwargs["knowledge_horizon_fnc"] = knowledge_horizons.ex_ante.__name__
        if "knowledge_horizon_par" not in kwargs:
            kwargs["knowledge_horizon_par"] = {
                knowledge_horizons.ex_ante.__code__.co_varnames[1]: "PT0H"
            }
        kwargs["name"] = kwargs["name"].replace(" ", "_").lower()
        if "display_name" not in kwargs:
            kwargs["display_name"] = humanize(kwargs["name"])

        super(Market, self).__init__(**kwargs)

        # Create a new Sensor with unique id across assets, markets and weather sensors
        if "id" not in kwargs:

            market_type = get_old_model_type(
                kwargs, MarketType, "market_type_name", "market_type"
            )

            generic_asset_kwargs = {
                **kwargs,
                **copy_old_sensor_attributes(
                    self,
                    old_sensor_type_attributes=[],
                    old_sensor_attributes=[
                        "display_name",
                    ],
                    old_sensor_type=market_type,
                ),
            }
            new_generic_asset = create_generic_asset("market", **generic_asset_kwargs)
            new_sensor = Sensor(
                name=kwargs["name"],
                generic_asset=new_generic_asset,
                **copy_old_sensor_attributes(
                    self,
                    old_sensor_type_attributes=[
                        "daily_seasonality",
                        "weekly_seasonality",
                        "yearly_seasonality",
                    ],
                    old_sensor_attributes=[
                        "display_name",
                    ],
                    old_sensor_type=market_type,
                ),
            )
            db.session.add(new_sensor)
            db.session.flush()  # generates the pkey for new_sensor
            new_sensor_id = new_sensor.id
        else:
            # The UI may initialize Market objects from API form data with a known id
            new_sensor_id = kwargs["id"]

        self.id = new_sensor_id

        # Copy over additional columns from (newly created) Market to (newly created) Sensor
        if "id" not in kwargs:
            db.session.add(self)
            db.session.flush()  # make sure to generate each column for the old sensor
            new_sensor.unit = self.unit
            new_sensor.event_resolution = self.event_resolution
            new_sensor.knowledge_horizon_fnc = self.knowledge_horizon_fnc
            new_sensor.knowledge_horizon_par = self.knowledge_horizon_par

    @property
    def entity_address_fm0(self) -> str:
        """Entity address under the fm0 scheme for entity addresses."""
        return build_entity_address(
            dict(market_name=self.name), "market", fm_scheme="fm0"
        )

    @property
    def entity_address(self) -> str:
        """Entity address under the latest fm scheme for entity addresses."""
        return build_entity_address(dict(sensor_id=self.id), "sensor")

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
    def price_unit(self) -> str:
        """Return the 'unit' property of the generic asset, just with a more insightful name."""
        return self.unit

    market_type = db.relationship(
        "MarketType", backref=db.backref("markets", lazy=True)
    )

    def __repr__(self):
        return "<Market %s:%r (%r) res.: %s>" % (
            self.id,
            self.name,
            self.market_type_name,
            self.event_resolution,
        )

    def to_dict(self) -> Dict[str, str]:
        return dict(name=self.name, market_type=self.market_type.name)


class Price(TimedValue, db.Model):
    """
    All prices are stored in one slim table.

    This model is now considered legacy. See TimedBelief.
    """

    sensor_id = db.Column(
        db.Integer(), db.ForeignKey("sensor.id"), primary_key=True, index=True
    )
    sensor = db.relationship("Sensor", backref=db.backref("prices", lazy=True))

    @classmethod
    def make_query(cls, **kwargs) -> Query:
        """Construct the database query."""
        return super().make_query(**kwargs)

    def __init__(self, use_legacy_kwargs: bool = True, **kwargs):
        # todo: deprecate the 'market_id' argument in favor of 'sensor_id' (announced v0.8.0)
        if "market_id" in kwargs and "sensor_id" not in kwargs:
            kwargs["sensor_id"] = tb_utils.replace_deprecated_argument(
                "market_id",
                kwargs["market_id"],
                "sensor_id",
                None,
            )
            kwargs.pop("market_id", None)

        # todo: deprecate the 'Price' class in favor of 'TimedBelief' (announced v0.8.0)
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

        super(Price, self).__init__(**kwargs)
