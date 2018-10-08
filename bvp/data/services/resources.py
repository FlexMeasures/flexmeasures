"""
Generic services for accessing asset data.
"""

from typing import List, Dict, Union, Optional
from datetime import datetime
from inflection import pluralize

from flask import current_app
from flask_security.core import current_user
from sqlalchemy.orm.query import Query
import pandas as pd

from bvp.data.config import db
from bvp.data.models.assets import AssetType, Asset, Power
from bvp.data.models.markets import Market
from bvp.data.models.user import User


class InvalidBVPAsset(Exception):
    pass


def get_markets() -> List[Market]:
    """Return a list of all Market objects.
    """
    return Market.query.order_by(Market.name.asc()).all()


def get_assets(owner_id: Optional[int] = None) -> List[Asset]:
    """Return a list of all Asset objects owned by current_user
     (or all users or a specific user - for this, admins can set an owner_id).
    """
    return _build_asset_query(owner_id).all()


def has_assets(owner_id: Optional[int] = None) -> bool:
    """Return True if the current user owns any assets.
     (or all users or a specific user - for this, admins can set an owner_id).
    """
    return _build_asset_query(owner_id).count() > 0


def can_access_asset(asset: Asset) -> bool:
    """Return True if the current user is an admin or the owner of the asset:"""
    if current_user.is_authenticated:
        if current_user.has_role("admin"):
            return True
        if asset.owner == current_user:
            return True
    return False


def _build_asset_query(owner_id: Optional[int] = None) -> Query:
    """Build an Asset query. Only authenticated users can use this.
    Admins can query for all assets (owner_id is None) or for any user (the asset's owner).
    Non-admins can only query for themselves (owner_id is ignored).
    """
    if current_user.is_authenticated:
        if current_user.has_role("admin"):
            if owner_id is not None:
                if not isinstance(owner_id, int):
                    try:
                        owner_id = int(owner_id)
                    except TypeError:
                        raise Exception(
                            "Owner id %s cannot be parsed as integer, thus seems to be invalid."
                            % owner_id
                        )
                return Asset.query.filter(Asset.owner_id == owner_id).order_by(
                    Asset.id.desc()
                )
            else:
                return Asset.query.order_by(Asset.id.desc())
        else:
            return Asset.query.filter_by(owner=current_user).order_by(Asset.id.desc())
    return Asset.query.filter(Asset.owner_id == -1)


def get_asset_groups() -> Dict[str, Query]:
    """
    An asset group is defined by Asset queries. Each query has a name, and we prefer pluralised names.
    They still need an executive call, like all(), count() or first()
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


def create_asset(
    display_name: str,
    asset_type_name: str,
    capacity_in_mw: float,
    latitude: float,
    longitude: float,
    min_soc_in_mwh: float,
    max_soc_in_mwh: float,
    soc_in_mwh: float,
    owner: User,
) -> Asset:
    """Validate input, create an asset and add it to the database"""
    if not "display_name":
        raise InvalidBVPAsset("No display name provided.")
    if capacity_in_mw < 0:
        raise InvalidBVPAsset("Capacity cannot be negative.")
    if latitude < -90 or latitude > 90:
        raise InvalidBVPAsset("Latitude must be between -90 and +90.")
    if longitude < -180 or longitude > 180:
        raise InvalidBVPAsset("Longitude must be between -180 and +180.")
    if owner is None:
        raise InvalidBVPAsset("Asset owner cannot be None.")
    if "Prosumer" not in owner.roles:
        raise InvalidBVPAsset("Owner must have role 'Prosumer'.")

    db_name = display_name.replace(" ", "-").lower()
    asset = Asset(
        display_name=display_name,
        name=db_name,
        capacity_in_mw=capacity_in_mw,
        latitude=latitude,
        longitude=longitude,
        asset_type_name=asset_type_name,
        min_soc_in_mwh=min_soc_in_mwh,
        max_soc_in_mwh=max_soc_in_mwh,
        soc_in_mwh=soc_in_mwh,
        owner=owner,
    )
    db.session.add(asset)
    return asset


def delete_asset(asset: Asset):
    """Delete the asset (and also its power measurements!). Requires admin privileges"""
    if "admin" not in current_user.roles:
        raise Exception("Only admins can delete assets.")
    else:
        db.session.delete(asset)
        current_app.logger.info("Deleted %s." % asset)


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
        horizon_window=(None, None),
        rolling: bool = True,
        sum_multiple: bool = True,
        create_if_empty: bool = False,
        as_beliefs: bool = None,
    ) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
        """Get data for one or more assets. TODO: market data?
        If the time range parameters are None, they will be gotten from the session.
        The horizon window will default to the latest measurement (anything more in the future than the
        end of the time interval."""

        asset_names = []
        for asset in self.assets:
            asset_names.append(asset.name)

        if as_beliefs is None:
            if len(asset_names) > 1 and sum_multiple:
                as_beliefs = False
            else:
                as_beliefs = True

        data = Power.collect(
            asset_names,
            query_window=(start, end),
            horizon_window=horizon_window,
            rolling=rolling,
            resolution=resolution,
            sum_multiple=sum_multiple,
            create_if_empty=create_if_empty,
            as_beliefs=as_beliefs,
        )
        return data
