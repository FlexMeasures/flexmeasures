from typing import List, Union, Optional, Dict
from itertools import groupby

from sqlalchemy.orm import Query

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.queries.utils import potentially_limit_assets_query_to_account


def query_assets_by_type(
    type_names: Union[List[str], str],
    account_id: Optional[int] = None,
    query: Optional[Query] = None,
) -> Query:
    """
    Return a query which looks for GenericAssets by their type.

    :param type_names: Pass in a list of type names or only one type name.
    :param account_id: Pass in an account ID if you want to query an account other than your own. This only works for admins. Public assets are always queried.
    :param query: Pass in an existing Query object if you have one.
    """
    if not query:
        query = GenericAsset.query
    query = query.join(GenericAssetType).filter(
        GenericAsset.generic_asset_type_id == GenericAssetType.id
    )
    if isinstance(type_names, str):
        query = query.filter(GenericAssetType.name == type_names)
    else:
        query = query.filter(GenericAssetType.name.in_(type_names))
    query = potentially_limit_assets_query_to_account(query, account_id)
    return query


def get_location_queries(account_id: Optional[int] = None) -> Dict[str, Query]:
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

    :param account_id: Pass in an account ID if you want to query an account other than your own. This only works for admins. Public assets are always queried.
    """
    asset_queries = {}
    all_assets = potentially_limit_assets_query_to_account(
        GenericAsset.query, account_id
    ).all()
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
        location_query = GenericAsset.query.filter(
            GenericAsset.name.in_([asset.name for asset in loc_group])
        )
        asset_queries[location_name] = potentially_limit_assets_query_to_account(
            location_query, account_id
        )
    return asset_queries


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
