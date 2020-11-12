from typing import Dict, List, Optional, Union
from datetime import timedelta

from sqlalchemy.orm import Query

from bvp.data.config import db
from bvp.data.models.time_series import TimedValue
from bvp.data.queries.utils import add_user_source_filter, add_source_type_filter
from bvp.utils.bvp_inflection import humanize


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


class Market(db.Model):
    """Each market is a pricing service."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True)
    display_name = db.Column(db.String(80), default="", unique=True)
    market_type_name = db.Column(
        db.String(80), db.ForeignKey("market_type.name"), nullable=False
    )
    unit = db.Column(db.String(80), default="", nullable=False)
    event_resolution = db.Column(
        db.Interval(), nullable=False, default=timedelta(minutes=0)
    )

    def __init__(self, **kwargs):
        super(Market, self).__init__(**kwargs)
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
    def make_query(
        cls,
        user_source_ids: Optional[Union[int, List[int]]] = None,
        source_types: Optional[List[str]] = None,
        **kwargs
    ) -> Query:
        query = super().make_query(asset_class=Market, **kwargs)
        if user_source_ids:
            query = add_user_source_filter(cls, query, user_source_ids)
        if source_types:
            query = add_source_type_filter(cls, query, source_types)
        return query

    def __init__(self, **kwargs):
        super(Price, self).__init__(**kwargs)
