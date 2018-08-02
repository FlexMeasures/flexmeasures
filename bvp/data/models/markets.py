from typing import Dict, Tuple, Union
from datetime import datetime, timedelta

from sqlalchemy.orm import Query, Session

from bvp.data.config import db
from bvp.data.models.data_sources import DataSource
from bvp.data.models.time_series import TimedValue


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

    @classmethod
    def make_query(
        cls,
        market_name: str,
        query_window: Tuple[datetime, datetime],
        horizon_window: Tuple[Union[None, timedelta], Union[None, timedelta]] = (
            None,
            None,
        ),
        rolling: bool = False,
        session: Session = None,
    ) -> Query:
        if session is None:
            session = db.session
        start, end = query_window
        # Todo: get data resolution for the market
        resolution = timedelta(minutes=15)
        start = (
            start - resolution
        )  # Adjust for the fact that we index time slots by their start time
        query = (
            session.query(Price.datetime, Price.value, Price.horizon, DataSource.label)
            .join(DataSource)
            .filter(Price.data_source_id == DataSource.id)
            .join(Market)
            .filter(Market.name == market_name)
            .filter((Price.datetime > start) & (Price.datetime < end))
        )
        earliest_horizon, latest_horizon = horizon_window
        if (
            earliest_horizon is not None
            and latest_horizon is not None
            and earliest_horizon == latest_horizon
        ):
            query = query.filter(Price.horizon == earliest_horizon)
        else:
            if earliest_horizon is not None:
                query = query.filter(Price.horizon >= earliest_horizon)
            if latest_horizon is not None:
                query = query.filter(Price.horizon <= latest_horizon)
        return query

    def __init__(self, **kwargs):
        super(Price, self).__init__(**kwargs)
