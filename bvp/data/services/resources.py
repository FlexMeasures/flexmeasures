"""
Generic services for accessing asset data.
"""

from typing import List, Dict, Union
from datetime import datetime
from inflection import pluralize

from flask_security.core import current_user
from sqlalchemy.orm.query import Query
import pandas as pd

from bvp.data.models.assets import AssetType, Asset, Power


def get_assets() -> List[Asset]:
    """Return a list of all Asset objects of current_user (or all for admins).
    The asset list is constructed lazily (only once per app start)."""
    if current_user.is_authenticated:
        if current_user.has_role("admin"):
            assets = Asset.query.order_by(Asset.id.desc()).all()
        else:
            assets = (
                Asset.query.filter_by(owner=current_user)
                .order_by(Asset.id.desc())
                .all()
            )
        return assets
    return []


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
        asset_queries[pluralize(asset_type.name)] = Asset.query.filter_by(
            asset_type_name=asset_type.name
        )

    if current_user.is_authenticated and not current_user.has_role("admin"):
        for name, query in asset_queries.items():
            asset_queries[name] = query.filter_by(owner=current_user)

    return asset_queries


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
          First, decide, if we want to call markets a "Resource". If so, get_data, should maybe just decide which data
          to fetch. I cannot imagine we ever want to mix data from assets and markets.
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
        return list(
            set([a.asset_type.name for a in self.assets])
        )  # list of unique asset type names in resource

    def get_data(
        self,
        start: datetime = None,
        end: datetime = None,
        resolution: str = None,
        sum_multiple: bool = True,
    ) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
        """Get data for one or more assets. TODO: market data?
        If the time range parameters are None, they will be gotten from the session."""
        asset_names = []
        for asset in self.assets:
            asset_names.append(asset.name)
        data = Power.collect(
            asset_names, start, end, resolution, sum_multiple=sum_multiple
        )
        return data
