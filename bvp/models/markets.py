from collections import namedtuple
from typing import Dict


class Market:
    """Each market is a pricing service.
    This class should only contain simple types, so it is easy to load/dump to Json.
    We only have one market for now.
    """

    # the name of the assorted MarketType
    market_type_name: str

    def __init__(self, name: str, market_type_name=None):
        self.orig_name = name
        self.market_type_name = market_type_name

    @property
    def name(self) -> str:
        """The name we actually want to use"""
        repr_name = self.orig_name
        return repr_name.replace(" ", "_").lower()

    @name.setter
    def name(self, new_name):
        self.name = new_name

    def to_dict(self) -> Dict[str, str]:
        return dict(name=self.name, market_type_name=self.market_type_name)


# queries reference attributes from Market to enable grouping and querying them
MarketQuery = namedtuple('MarketQuery', 'attr val')


# a market group is defined by OR-linked market queries
market_groups = dict(
        fixed_tariff=(MarketQuery(attr="market_type_name", val="fixed_tariff"),),
        dynamic_tariff=(MarketQuery(attr="market_type_name", val="dynamic_tariff"),),
        tariff=(MarketQuery(attr="market_type_name", val="fixed_tariff"),
                MarketQuery(attr="market_type_name", val="dynamic_tariff")),
        day_ahead=(MarketQuery(attr="market_type_name", val="day_ahead"),),
    )


class MarketType:
    """Describing market types for our purposes"""

    name: str = None

    # Assumptions about the time series data set, such as normality and stationarity
    # For now, this is usable input for Prophet (see init), but it might evolve.
    preconditions = Dict[str, bool]

    def __init__(self, name: str,
                 daily_seasonality: bool=False, weekly_seasonality: bool=False, yearly_seasonality: bool=False):
        self.name = name

        self.preconditions = dict(
            daily_seasonality=daily_seasonality,
            weekly_seasonality=weekly_seasonality,
            yearly_seasonality=yearly_seasonality
        )


market_types = dict(
    fixed_tariff=MarketType("fixed_tariff"),
    dynamic_tariff=MarketType("dynamic_tariff", daily_seasonality=True, weekly_seasonality=True,
                              yearly_seasonality=True),
    day_ahead=MarketType("day_ahead", daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=True)
)
