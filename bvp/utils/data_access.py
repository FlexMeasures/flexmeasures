"""
Utils for accessing data.
Markets meta data as well as the actual numbers are lazily loaded in here.
Also, the Resource class is here, which virtually sits on top of assets.
"""

from typing import List, Dict, Union, Optional
import json
import os
import datetime
from inflection import pluralize

from flask import session, current_app
from flask_security.core import current_user
from werkzeug.exceptions import BadRequest
import pandas as pd
from sqlalchemy.orm.query import Query

from bvp.models.assets import Asset, AssetType
from bvp.models.markets import Market
from bvp.utils import time_utils


# global, lazily loaded market description
MARKETS = []
# global, lazily loaded data source, will be replaced by DB connection probably
DATA = {}


def get_assets() -> List[Asset]:
    """Return a list of all models.Asset objects that are mentioned in assets.json and have data.
    The asset list is constructed lazily (only once per app start)."""
    result = list()
    if current_user.is_authenticated:
        if current_user.has_role("admin"):
            assets = Asset.query.order_by(Asset.id.desc())
        else:
            assets = Asset.query.filter_by(owner=current_user).order_by(Asset.id.desc())
        for asset in assets:
            has_data = True
            if not os.path.exists("data/pickles/df_%s_res15T.pickle" % asset.name):
                has_data = False
            if has_data:
                result.append(asset)
    return result


def get_asset_groups() -> Dict[str, Query]:
    """
    An asset group is defined by Asset queries. Each query has a name, and we prefer pluralised names.
    They still need a executive call, like all(), count() or first()
    """
    # 1. Custom asset groups by combinations of asset types
    asset_queries = dict(
            renewables=(Asset.query.filter(Asset.asset_type_name.in_(["solar", "wind"])))
        )
    # 2. We also include a group per asset type - using the pluralised asset type name
    for asset_type in AssetType.query.all():
        asset_queries[pluralize(asset_type.name)] = Asset.query.filter_by(asset_type_name=asset_type.name)

    if current_user.is_authenticated and not current_user.has_role("admin"):
        for name, query in asset_queries.items():
            asset_queries[name] = query.filter_by(owner=current_user)

    return asset_queries


def get_markets() -> List[Market]:
    """Return markets. Markets are loaded lazily from file."""
    global MARKETS
    if len(MARKETS) == 0:
        with open("data/markets.json", "r") as markets_json:
            dict_markets = json.loads(markets_json.read())
        MARKETS = [Market(**a) for a in dict_markets]
    return MARKETS


def get_data_for_assets(asset_names: List[str], start: datetime=None, end: datetime=None, resolution: str=None,
                        sum_multiple=True) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """Get data for one or more assets (also markets).
    We (lazily) look up by pickle, so we require a list of asset or market names.
    If the time range parameters are None, they will be gotten from the session.
    Response is a 2D data frame with the usual columns (y, yhat, ...).
    If data from multiple assets is retrieved, the results are being summed.
    If sum_multiple is False, the response will be a dictionary with asset names as keys and data frames as values.
    Response might be None if no data exists for these assets in this time range."""
    data_as_dict: Dict[str, pd.DataFrame] = None
    data_as_df: pd.DataFrame = None
    if start is None or end is None or resolution is None and "resolution" not in session:
        time_utils.set_time_range_for_session()
    if start is None:
        start = session["start_time"]
    if end is None:
        end = session["end_time"]
    if resolution is None:
        resolution = session["resolution"]
    for asset_name in asset_names:
        global DATA
        if asset_name not in DATA:
            current_app.logger.info("Loading %s data from disk ..." % asset_name)
            try:
                DATA[asset_name] = pd.read_pickle("data/pickles/df_%s_res15T.pickle" % asset_name)
            except FileNotFoundError:
                raise BadRequest("Sorry, we cannot find any data for the resource \"%s\" ..." % asset_name)

        date_mask = (DATA[asset_name].index >= start) & (DATA[asset_name].index <= end)
        data = DATA[asset_name].loc[date_mask].resample(resolution).mean()

        if sum_multiple is True:  # Here we only build one data frame, summed up if necessary.
            if data_as_df is None:
                data_as_df = data
            else:
                data_as_df = data_as_df.add(data)
        else:                     # Here we build a dict with data frames.
            if data_as_dict is None:
                data_as_dict = {asset_name: data}
            else:
                data_as_dict[asset_name] = data
    if sum_multiple is True:
        return data_as_df
    else:
        return data_as_dict


def extract_forecasts(df: pd.DataFrame) -> pd.DataFrame:
    """Extract forecast columns (given the chosen horizon) and give them the standard naming"""
    forecast_columns = ["yhat", "yhat_upper", "yhat_lower"]  # this is what the plotter expects
    horizon = session["forecast_horizon"]
    forecast_renaming = {"yhat_%s" % horizon: "yhat",
                         "yhat_%s_upper" % horizon: "yhat_upper",
                         "yhat_%s_lower" % horizon:  "yhat_lower"}
    return df.rename(forecast_renaming, axis="columns")[forecast_columns]


class Resource:
    """
    This class represents a resource and helps to map names to assets.
    A "resource" is an umbrella term:

    * It can be one asset / market.
    * It can be a group of assets / markets. (see get_asset_groups)

    The class itself defines only one thing: a resource name.
    The class methods provide helpful functions to get from resource name to assets and their time series data.

    Typical usages might thus be:

    * Resource(session["resource"]).assets
    * Resource(session["resource"]).display_name
    * Resource(session["resource"]).get_data()

    TODO: The link to markets still needs some care (best to do that once we have modeled markets better)
    """

    last_loaded_asset_list = []  # this can be used to avoid loading assets more than once during one call stack

    def __init__(self, name):
        if name is None or name == "":
            raise Exception("Empty resource name passed (%s)" % name)
        self.name = name

    @property
    def assets(self) -> List[Asset]:
        """Gather assets which are identified by this resource's name.
        The resource name is either the name of an asset group or an individual asset."""
        assets = []
        asset_groups = get_asset_groups()
        if self.name in asset_groups:
            for asset in asset_groups[self.name]:
                assets.append(asset)
        else:
            asset = Asset.query.filter_by(name=self.name).one_or_none()
            if asset is not None:
                assets = [asset]
        self.last_loaded_asset_list = assets
        return assets

    @property
    def is_unique_asset(self) -> bool:
        """Determines whether the resource represents a unique asset."""
        return [self.name] == [a.name for a in self.assets]

    @property
    def display_name(self) -> str:
        """Attempt to get a beautiful name to show if possible."""
        if self.is_unique_asset:
            return self.assets[0].display_name
        return self.name

    @property
    def unique_asset_type_names(self) -> List[str]:
        """Return list of unique asset types represented by this resource."""
        return list(set([a.asset_type.name for a in self.assets]))  # list of unique asset type names in resource

    def get_market(self) -> Optional[Market]:
        """Find a market. TODO: support market grouping (see models.market_groups)."""
        markets = get_markets()
        for market in markets:
            if market.name == self.name:
                return market

    def get_data(self, start: datetime=None, end: datetime=None, resolution: str=None,
                 sum_multiple: bool=True) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
        """Get data for one or more assets or markets.
        If the time range parameters are None, they will be gotten from the session.
        See utils.data_access.get_data_vor_assets for more information."""
        asset_names = []
        for asset in self.assets:
            asset_names.append(asset.name)
        market = self.get_market()
        if market is not None:
            asset_names.append(market.name)
        data = get_data_for_assets(asset_names, start, end, resolution, sum_multiple=sum_multiple)
        if data is None or data.size == 0:
            raise BadRequest("Not enough data available for resource \"%s\" in the time range %s to %s"
                             % (self.name, start, end))
        return data
