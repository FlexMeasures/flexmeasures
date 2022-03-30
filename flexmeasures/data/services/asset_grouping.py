"""
Convenience functions and class for accessing generic assets in groups.
For example, group by asset type or by location.
"""

from __future__ import annotations
from typing import List, Dict, Optional, Union
import inflect

from flask_security.core import current_user
from sqlalchemy.orm import Query

from flexmeasures.auth.policy import ADMIN_ROLE
from flexmeasures.utils.flexmeasures_inflection import parameterize, pluralize
from flexmeasures.data.models.generic_assets import (
    GenericAssetType,
    GenericAsset,
    assets_share_location,
)
from flexmeasures.data.queries.generic_assets import (
    query_assets_by_type,
    get_location_queries,
)

p = inflect.engine()


def get_asset_group_queries(
    custom_additional_groups: Optional[Dict[str, List[str]]] = None,
    group_by_location: bool = False,
) -> Dict[str, Query]:
    """
    An asset group is defined by Asset queries. Each query has a name, and we prefer pluralised names.
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

    asset_queries = mask_inaccessible_assets(asset_queries)

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
        Decide whether comparing individual traces for assets in this asset group
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


def mask_inaccessible_assets(
    asset_queries: Union[Query, Dict[str, Query]]
) -> Union[Query, Dict[str, Query]]:
    """Filter out any assets that the user should not be able to access.

    We do not explicitly check user authentication here, because non-authenticated users are not admins
    and have no asset ownership, so applying this filter for non-admins masks all assets.
    """
    if not current_user.has_role(ADMIN_ROLE):
        if isinstance(asset_queries, dict):
            for name, query in asset_queries.items():
                asset_queries[name] = query.filter(
                    GenericAsset.owner == current_user.account
                )
        else:
            asset_queries = asset_queries.filter(
                GenericAsset.owner == current_user.account
            )
    return asset_queries
