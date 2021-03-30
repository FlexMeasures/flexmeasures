from typing import Dict

import timely_beliefs as tb
from timely_beliefs.sensors.func_store import knowledge_horizons
from sqlalchemy.orm import Query

from flexmeasures.data.config import db
from flexmeasures.data.models.time_series import Sensor, TimedValue
from flexmeasures.utils.flexmeasures_inflection import humanize


class MarketType(db.Model):
    """Describing market types for our purposes.
    TODO: Add useful attributes like frequency (e.g. 1H) and the meaning of units (e.g. Mwh).
    """

    name = db.Column(db.String(80), primary_key=True)
    display_name = db.Column(db.String(80), default="", unique=True)

    daily_seasonality = db.Column(db.Boolean(), nullable=False, default=False)
    weekly_seasonality = db.Column(db.Boolean(), nullable=False, default=False)
    yearly_seasonality = db.Column(db.Boolean(), nullable=False, default=False)

    def __init__(self, **kwargs):
        super(MarketType, self).__init__(**kwargs)
        self.name = self.name.replace(" ", "_").lower()
        if "display_name" not in kwargs:
            self.display_name = humanize(self.name)

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
    """Each market is a pricing service."""

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

        # Create a new Sensor with unique id across assets, markets and weather sensors
        if "id" not in kwargs:
            new_sensor = Sensor(name=kwargs["name"])
            db.session.add(new_sensor)
            db.session.flush()  # generates the pkey for new_sensor
            new_sensor_id = new_sensor.id
        else:
            # The UI may initialize Market objects from API form data with a known id
            new_sensor_id = kwargs["id"]

        super(Market, self).__init__(**kwargs)
        self.id = new_sensor_id
        self.name = self.name.replace(" ", "_").lower()
        if "display_name" not in kwargs:
            self.display_name = humanize(self.name)

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
    TODO: datetime objects take up most of the space (12 bytes each)). One way out is to normalise them out to a table.
    """

    market_id = db.Column(
        db.Integer(), db.ForeignKey("market.id"), primary_key=True, index=True
    )
    market = db.relationship("Market", backref=db.backref("prices", lazy=True))

    @classmethod
    def make_query(cls, **kwargs) -> Query:
        """Construct the database query."""
        return super().make_query(asset_class=Market, **kwargs)

    def __init__(self, **kwargs):
        super(Price, self).__init__(**kwargs)
