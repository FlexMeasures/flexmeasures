"""
Convenience functions and class for accessing generic assets in groups.
For example, group by asset type or by location.
"""

from __future__ import annotations
from typing import List, Dict, Optional, Union
import inflect
from itertools import groupby

from sqlalchemy.orm import Query
from flask_security import current_user
from werkzeug.exceptions import Forbidden
from flexmeasures.auth.policy import ADMIN_ROLE, ADMIN_READER_ROLE

from flexmeasures.utils.flexmeasures_inflection import parameterize, pluralize
from flexmeasures.data.models.generic_assets import (
    GenericAssetType,
    GenericAsset,
    assets_share_location,
)
from flexmeasures.data.queries.generic_assets import query_assets_by_type

p = inflect.engine()


def get_asset_group_queries(
    custom_additional_groups: Optional[Dict[str, List[str]]] = None,
    group_by_location: bool = False,
) -> Dict[str, Query]:
    """
    An asset group is defined by Asset queries. Each query has a name, and we prefer pluralised  names.
    They still need an executive call, like all(), count() or first().

    This function limits the assets to be queried to the current user's account,
    if the user is not an admin.

    Note: Make sure the current user has the "read" permission on his account (on GenericAsset.__class__?? See https://github.com/FlexMeasures/flexmeasures/issues/200).

    :param custom_additional_groups: dict of asset type groupings (mapping group names to names of asset types). See also the setting FLEXMEASURES_ASSET_TYPE_GROUPS.
    :param group_by_location: If True, groups will be made for assets at the same location. Naming of the location currently supports charge points (for EVSEs).
    """
    asset_queries = {}

    # 1. Custom asset groups by combinations of asset types
    if custom_additional_groups:
        for asset_type_group_name, asset_types in custom_additional_groups.items():
            asset_queries[asset_type_group_name] = query_assets_by_type(asset_types)

    # 2. We also include a group per asset type - using the pluralised asset type name
    for asset_type in GenericAssetType.query.all():
        asset_queries[pluralize(asset_type.name)] = query_assets_by_type(
            asset_type.name
        )

    # 3. Finally, we group assets by location
    if group_by_location:
        asset_queries.update(get_location_queries())

    if not (
        current_user.has_role(ADMIN_ROLE) or current_user.has_role(ADMIN_READER_ROLE)
    ):
        # only current user's account
        asset_queries = limit_assets_to_account(asset_queries)

    return asset_queries


def get_location_queries() -> Dict[str, Query]:
    """
    Make queries for grouping assets by location.

    We group EVSE assets by location (if they share a location, they belong to the same Charge Point)
    Like get_asset_group_queries, the values in the returned dict still need an executive call, like all(), count() or first(). Note that this function will still load and inspect assets to do its job.

    The Charge Points are named on the basis of the first EVSE in their list,
    using either the whole EVSE name or that part that comes before a " -" delimiter. For example:
    If:
        evse_name = "Seoul Hilton - charger 1"
    Then:
        charge_point_name = "Seoul Hilton (Charge Point)"

    A Charge Point is a special case. If all assets on a location are of type EVSE,
    we can call the location a "Charge Point".
    """
    asset_queries = {}
    all_assets = GenericAsset.query.all()
    loc_groups = group_assets_by_location(all_assets)
    for loc_group in loc_groups:
        if len(loc_group) == 1:
            continue
        location_type = "(Location)"
        if all(
            [
                asset.asset_type.name in ["one-way_evse", "two-way_evse"]
                for asset in loc_group
            ]
        ):
            location_type = "(Charge Point)"
        location_name = f"{loc_group[0].name.split(' -')[0]} {location_type}"
        asset_queries[location_name] = GenericAsset.query.filter(
            GenericAsset.name.in_([asset.name for asset in loc_group])
        )
    return asset_queries


def limit_assets_to_account(
    asset_queries: Union[Query, Dict[str, Query]]
) -> Union[Query, Dict[str, Query]]:
    """Filter out any assets that are not in the user's account."""
    if not hasattr(current_user, "account_id"):
        raise Forbidden("Unauthenticated user cannot list asset groups.")
    if isinstance(asset_queries, dict):
        for name, query in asset_queries.items():
            asset_queries[name] = query.filter(
                GenericAsset.account_id == current_user.account.id
            )
    else:
        asset_queries = asset_queries.filter(
            GenericAsset.account_id == current_user.account_id
        )
    return asset_queries


class AssetGroup:
    """
    This class represents a group of assets of the same type, offering some convenience functions
    for displaying their properties.

    When initialised with an asset type name, the group will contain all assets of
    the given type that are accessible to the current user's account.

    When initialised with a query for GenericAssets, as well, the group will list the assets returned by that query. This can be useful in combination with get_asset_group_queries,
    see above.

    TODO: On a conceptual level, we can model two functionally useful ways of grouping assets:
    - AggregatedAsset if it groups assets of only 1 type,
    - GeneralizedAsset if it groups assets of multiple types
    There might be specialised subclasses, as well, for certain groups, like a market and consumers.
    """

    name: str
    assets: List[GenericAsset]
    count: int
    unique_asset_types: List[GenericAssetType]
    unique_asset_type_names: List[str]

    def __init__(self, name: str, asset_query: Optional[Query] = None):
        """The asset group name is either the name of an asset group or an individual asset."""
        if name is None or name == "":
            raise Exception("Empty asset (group) name passed (%s)" % name)
        self.name = name

        if not asset_query:
            asset_query = GenericAsset.query.filter_by(name=self.name)

        # List unique asset types and asset type names represented by this group
        self.assets = asset_query.all()
        self.unique_asset_types = list(set([a.asset_type for a in self.assets]))
        self.unique_asset_type_names = list(
            set([a.asset_type.name for a in self.assets])
        )

        # Count all assets that are identified by this group's name
        self.count = len(self.assets)

    @property
    def is_unique_asset(self) -> bool:
        """Determines whether the resource represents a unique asset."""
        return [self.name] == [a.name for a in self.assets]

    @property
    def display_name(self) -> str:
        """Attempt to get a beautiful name to show if possible."""
        if self.is_unique_asset:
            return self.assets[0].name
        return self.name

    def is_eligible_for_comparing_individual_traces(self, max_traces: int = 7) -> bool:
        """
        Decide whether comparing individual traces for assets in this resource
        is a useful feature.
        The number of assets that can be compared is parametrizable with max_traces.
        Plot colors are reused if max_traces > 7, and run out if max_traces > 105.
        """
        return len(self.assets) in range(2, max_traces + 1) and assets_share_location(
            self.assets
        )

    @property
    def hover_label(self) -> Optional[str]:
        """Attempt to get a hover label to show if possible."""
        label = p.join(
            [
                asset_type.description
                for asset_type in self.unique_asset_types
                if asset_type.description is not None
            ]
        )
        return label if label else None

    @property
    def parameterized_name(self) -> str:
        """Get a parametrized name for use in javascript."""
        return parameterize(self.name)

    def __str__(self):
        return self.display_name


def group_assets_by_location(
    asset_list: List[GenericAsset],
) -> List[List[GenericAsset]]:
    groups = []

    def key_function(x):
        return x.location if x.location else ()

    sorted_asset_list = sorted(asset_list, key=key_function)
    for _k, g in groupby(sorted_asset_list, key=key_function):
        groups.append(list(g))
    return groups
