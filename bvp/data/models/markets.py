from typing import Dict

from bvp.data.config import db
from bvp.data.models import TimedValue


class MarketType(db.Model):
    """Describing market types for our purposes.
    TODO: Add useful attributes like frequency (e.g. 1H) and the meaning of units (e.g. Mwh).
    """

    name = db.Column(db.String(80), primary_key=True)

    daily_seasonality = db.Column(db.Boolean(), nullable=False, default=False)
    weekly_seasonality = db.Column(db.Boolean(), nullable=False, default=False)
    yearly_seasonality = db.Column(db.Boolean(), nullable=False, default=False)

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


class Market(db.Model):
    """Each market is a pricing service.
    We only have one market for now.
    TODO: Add useful attributes like currency.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True)
    market_type_name = db.Column(
        db.String(80), db.ForeignKey("market_type.name"), nullable=False
    )

    def __init__(self, **kwargs):
        super(Market, self).__init__(**kwargs)
        self.name = self.name.replace(" ", "_").lower()

    market_type = db.relationship(
        "MarketType", backref=db.backref("markets", lazy=True)
    )

    def __repr__(self):
        return "<Market %r (%r)>" % (self.name, self.market_type_name)

    def to_dict(self) -> Dict[str, str]:
        return dict(name=self.name, market_type=self.market_type.name)


class Price(TimedValue, db.Model):
    """
    All prices are stored in one slim table.
    TODO: datetime objects take up most of the space (12 bytes each)). One way out is to normalise them out to a table.
    """

    market_id = db.Column(db.Integer(), db.ForeignKey("market.id"), primary_key=True)
    market = db.relationship("Market", backref=db.backref("prices", lazy=True))
