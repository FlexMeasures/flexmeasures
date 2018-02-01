from collections import namedtuple
from typing import Dict


# Time resolutions
resolutions = ["15T", "1h", "1d", "1w"]

# The confidence interval for forecasting
confidence_interval_width = .9


class Asset:
    """Each asset is a consuming or producing hardware.
    This class should only contain simple types, so it is easy to load/dump to Json."""

    # the name of the assorted AssetType
    asset_type_name: str
    # not used yet
    area_code: str

    def __init__(self, name: str, asset_type_name=None, area_code=""):
        self.orig_name = name
        self.asset_type_name = asset_type_name
        self.area_code = area_code

    @property
    def name(self) -> str:
        """The name we actually want to use"""
        repr_name = self.orig_name
        if self.asset_type_name == "solar":
            repr_name = repr_name.replace(" (MW)", "")
        return repr_name.replace(" ", "_").lower()

    @name.setter
    def name(self, new_name):
        self.name = new_name


    @property
    def asset_type(self):
        return asset_types.get(self.asset_type_name, None)

    def to_dict(self) -> Dict[str, str]:
        return dict(name=self.name, asset_type_name=self.asset_type_name, area_code=self.area_code)


# queries reference attributes from Asset to enable grouping and querying them
AssetQuery = namedtuple('AssetQuery', 'attr val')


# an asset group is defined by OR-linked asset queries
asset_groups = dict(
        solar=(AssetQuery(attr="asset_type_name", val="solar"),),
        wind=(AssetQuery(attr="asset_type_name", val="wind"),),
        renewables=(AssetQuery(attr="asset_type_name", val="solar"),
                    AssetQuery(attr="asset_type_name", val="wind")),
        vehicles=(AssetQuery(attr="asset_type_name", val="ev"),)
    )


class AssetType:
    """Describing asset types for our purposes"""

    # Assumptions about the time series data set, such as normality and stationarity
    # For now, this is usable input for Prophet (see init), but it might evolve.
    preconditions = Dict[str, bool]

    def __init__(self, name: str,
                 is_consumer: bool=False, is_producer: bool=False,
                 daily_seasonality: bool=False, weekly_seasonality: bool=False, yearly_seasonality: bool=False):
        self.name = name
        self.is_consumer = is_consumer
        self.is_producer = is_producer

        self.preconditions = dict(
            daily_seasonality=daily_seasonality,
            weekly_seasonality=weekly_seasonality,
            yearly_seasonality=yearly_seasonality
        )


asset_types = dict(
    solar=AssetType("solar", is_producer=True, daily_seasonality=True, yearly_seasonality=True),
    wind=AssetType("wind", is_producer=True, daily_seasonality=True, yearly_seasonality=True),
    ev=AssetType("ev", is_consumer=True, daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=True)
    # Todo: add holidays?
)


class Market:
    """Each market is a pricing service.
    This class should only contain simple types, so it is easy to load/dump to Json."""

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
