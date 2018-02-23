from collections import namedtuple
from typing import Dict, List, Tuple, Union, Optional
from random import random
import datetime

import pandas as pd
import inflection
from inflection import pluralize, titleize

from utils import data_access


# Time resolutions
resolutions = ["15T", "1h", "1d", "1w"]

# The confidence interval for forecasting
confidence_interval_width = .9

# Give the inflection module some help for our domain
inflection.UNCOUNTABLES.add("solar")
inflection.UNCOUNTABLES.add("wind")


def random_jeju_island_location() -> Tuple[float, float]:
    """ Temporary helper for randomizing locations of assets on the island
    (for which we have no real location). TODO: make obsolete? """
    return 33.3 + random() * 0.2, 126.25 + random() * .65


def get_capacity_for(asset_name: str, asset_type_name: str) -> float:
    """Temporary helper to guess a maximum capacity from the data we have"""
    if asset_type_name in ("ev", "building"):
        return -1 * min(pd.read_pickle("data/pickles/df_%s_res15T.pickle" % asset_name).y)
    else:
        return max(pd.read_pickle("data/pickles/df_%s_res15T.pickle" % asset_name).y)


class ModelException(Exception):
    pass


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

    @property
    def pluralized_name(self):
        return pluralize(self.name)


asset_types = dict(
    solar=AssetType("solar", is_producer=True, daily_seasonality=True, yearly_seasonality=True),
    wind=AssetType("wind", is_producer=True, daily_seasonality=True, yearly_seasonality=True),
    charging_station=AssetType("charging_station", is_consumer=True, daily_seasonality=True, weekly_seasonality=True,
                               yearly_seasonality=True),
    battery=AssetType("battery", is_consumer=True, is_producer=True,
                      daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=True),
    building=AssetType("building", is_consumer=True, daily_seasonality=True, weekly_seasonality=True,
                       yearly_seasonality=True)
    # Todo: add holidays?
)


class Asset:
    """Each asset is a consuming or producing hardware.
    This class should only contain simple types, so it is easy to load/dump to Json."""

    # The name of the assorted AssetType
    asset_type_name: str
    # The name we want to see
    _display_name: str
    # How many MW at peak usage
    capacity_in_mw: float
    # A tuple of latitude (North/South coordinate) and longitude (East/West coordinate)
    location = Tuple[float, float]

    def __init__(self, name: str, asset_type_name: str, display_name: str="", capacity_in_mw: float=0,
                 location: Tuple[float, float]=None):
        self.orig_name = name  # The original name of a data source can be used here and the name will be adapted.
        self._display_name = display_name
        self.asset_type_name = asset_type_name
        self.capacity_in_mw = capacity_in_mw
        self.location = location
        if self.location is None:
            self.location = random_jeju_island_location()

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
    def display_name(self):
        if self._display_name == "":
            return titleize(self.name)
        return self._display_name

    @display_name.setter
    def display_name(self, new_name):
        self._display_name = new_name

    @property
    def asset_type(self) -> AssetType:
        return asset_types.get(self.asset_type_name, None)

    @property
    def asset_type_display_name(self) -> str:
        return titleize(self.asset_type_name)

    def capacity_factor_in_percent_for(self, load_in_mw) -> int:
        if self.capacity_in_mw == 0:
            return 0
        return min(round((load_in_mw / self.capacity_in_mw) * 100, 2), 100)

    def to_dict(self) -> Dict[str, str]:
        return dict(name=self.name,
                    display_name=self.display_name,
                    asset_type_name=self.asset_type_name,
                    location=self.location,
                    capacity_in_mw=self.capacity_in_mw)


# queries reference attributes from Asset to enable grouping and querying them
AssetQuery = namedtuple('AssetQuery', 'attr val')


# an asset group is defined by OR-linked asset queries
asset_groups = dict(
        renewables=(AssetQuery(attr="asset_type_name", val="solar"),
                    AssetQuery(attr="asset_type_name", val="wind")),
    )
# we also include a group per asset type
for asset_type in asset_types:
    asset_groups[pluralize(asset_type)] = (AssetQuery(attr="asset_type_name", val=asset_type), )


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


class Resource:
    """
    This class represents a resource, which holds not more data than a resource name.
    A resource is an umbrella term:

    * It can be one asset / market.
    * It can be a group of assets / markets.

    This class provides helpful functions to get from resource name to assets.
    TODO: The link to markets still needs some care (best to do that once we have modeled markets better)
    """

    _ASSETS: List[Asset] = None

    def __init__(self, name):
        if name is None or name == "":
            raise ModelException("Empty name passed (%s)" % name)
        self.name = name

    @property
    def assets(self) -> List[Asset]:
        """Gather assets (lazily) which are identified by this resource name.
        The resource name is either the name of an asset group or an individual asset."""
        if self._ASSETS is None:
            self._ASSETS = data_access.get_assets()
        if self.name in asset_groups:
            resource_assets = set()
            asset_queries = asset_groups[self.name]
            for query in asset_queries:
                for asset in self._ASSETS:
                    if hasattr(asset, query.attr) and getattr(asset, query.attr, None) == query.val:
                        resource_assets.add(asset)
            if len(resource_assets) > 0:
                return list(resource_assets)
        for asset in self._ASSETS:
            if asset.name == self.name:
                return [asset]
        return []

    @property
    def is_pure_consumer(self) -> bool:
        """Return True if the assets represented by this resource are consuming but not producing.
        Currently only checks the first asset."""
        only_or_first_asset = self.assets[0]
        if (only_or_first_asset is not None
                and asset_types[only_or_first_asset.asset_type_name].is_consumer
                and not asset_types[only_or_first_asset.asset_type_name].is_producer):
            return True
        else:
            return False

    def is_pure_producer(self) -> bool:
        """Return True if the assets represented by this resource are producing but not consuming.
        Currently only checks the first asset."""
        only_or_first_asset = self.assets[0]
        if (only_or_first_asset is not None
                and asset_types[only_or_first_asset.asset_type_name].is_producer
                and not asset_types[only_or_first_asset.asset_type_name].is_consumer):
            return True
        else:
            return False

    @property
    def is_unique_asset(self) -> bool:
        """Determines whether the resource represents a unique asset."""
        return [self.name] == [a.name for a in self.assets]

    @property
    def unique_asset_type_names(self) -> List[str]:
        """Return list of unique asset types represented by this resoure."""
        return list(set([a.asset_type.name for a in self.assets]))  # list of unique asset type names in resource

    def get_market(self) -> Optional[Market]:
        """Find a market. TODO: support market grouping (see models.market_groups)."""
        markets = data_access.get_markets()
        for market in markets:
            if market.name == self.name:
                return market

    def get_data(self, start: datetime=None, end: datetime=None, resolution: str=None,
                 sum_multiple: bool=True) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
        """Get data for one or more assets or markets.
        If the time range parameters are None, they will be gotten from the session.
        See get_data_vor_assets for more information."""
        asset_names = []
        for asset in self.assets:
            asset_names.append(asset.name)
        market = self.get_market()
        if market is not None:
            asset_names.append(market.name)
        return data_access.get_data_for_assets(asset_names, start, end, resolution, sum_multiple=sum_multiple)