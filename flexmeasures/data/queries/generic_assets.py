from typing import List, Union, Optional, Dict
from itertools import groupby
from flask_login import current_user

from sqlalchemy.orm import Query
from flexmeasures.auth.policy import user_has_admin_access

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.user import Account
from flexmeasures.data.queries.utils import potentially_limit_assets_query_to_account
from flexmeasures.utils.flexmeasures_inflection import pluralize


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


def get_asset_group_queries(
    group_by_type: bool = True,
    group_by_account: bool = False,
    group_by_location: bool = False,
    custom_aggregate_type_groups: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Query]:
    """
    An asset group is defined by Asset queries, which this function can generate.
    Each query has a name (for the asset group it represents).
    These queries still need an executive call, like all(), count() or first().
    This function limits the assets to be queried to the current user's account,
    if the user is not an admin.
    Note: Make sure the current user has the "read" permission on their account (on GenericAsset.__class__?? See https://github.com/FlexMeasures/flexmeasures/issues/200) or is an admin.
    :param group_by_type: If True, groups will be made for assets with the same type. We prefer pluralised group names here. Defaults to True.
    :param group_by_account: If True, groups will be made for assets within the same account. This makes sense for admins, as they can query across accounts.
    :param group_by_location: If True, groups will be made for assets at the same location. Naming of the location currently supports charge points (for EVSEs).
    :param custom_aggregate_type_groups: dict of asset type groupings (mapping group names to names of asset types). See also the setting FLEXMEASURES_ASSET_TYPE_GROUPS.
    """
    asset_queries = {}

    # 1. Custom asset groups by combinations of asset types
    if custom_aggregate_type_groups:
        for asset_type_group_name, asset_types in custom_aggregate_type_groups.items():
            asset_queries[asset_type_group_name] = query_assets_by_type(asset_types)

    # 2. Include a group per asset type - using the pluralised asset type name
    if group_by_type:
        for asset_type in GenericAssetType.query.all():
            asset_queries[pluralize(asset_type.name)] = query_assets_by_type(
                asset_type.name
            )

    # 3. Include a group per account (admins only)  # TODO: we can later adjust this for accounts who admin certain others, not all
    if group_by_account and user_has_admin_access(current_user, "read"):
        for account in Account.query.all():
            asset_queries[account.name] = GenericAsset.query.filter(
                GenericAsset.account_id == account.id
            )

    # 4. Finally, we can group assets by location
    if group_by_location:
        asset_queries.update(get_location_queries())

    return asset_queries
