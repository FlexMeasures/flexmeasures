"""
Convenience functions and class for accessing generic assets in groups.
For example, group by asset type or by location.
"""

from __future__ import annotations
from typing import List, Optional
import inflect

from sqlalchemy.orm import Query

from flexmeasures.utils.flexmeasures_inflection import parameterize
from flexmeasures.data.models.generic_assets import (
    GenericAssetType,
    GenericAsset,
    assets_share_location,
)

p = inflect.engine()


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
