from typing import Dict, List, Tuple

import pandas as pd
import timely_beliefs as tb

from flexmeasures.data.models.assets import Asset, AssetType
from flexmeasures.data.models.markets import Market
from flexmeasures.data.queries.utils import simplify_index
from flexmeasures.data.services.resources import Resource


def get_structure(
    assets: List[Asset],
) -> Tuple[Dict[str, AssetType], List[Market], Dict[str, Resource]]:
    """Get asset portfolio structured as Resources, based on AssetTypes present in a list of Assets.

    Initializing Resources leads to some database queries.

    :param assets: a list of Assets
    :returns: a tuple comprising:
              - a dictionary of resource names (as keys) and the asset type represented by these resources (as values)
              - a list of (unique) Markets that are relevant to these resources
              - a dictionary of resource names (as keys) and Resources (as values)
    """

    # Set up a resource name for each asset type
    represented_asset_types = {
        asset_type.plural_name: asset_type
        for asset_type in [asset.asset_type for asset in assets]
    }

    # Load structure (and set up resources)
    resource_dict = {}
    markets: List[Market] = []
    for resource_name in represented_asset_types.keys():
        resource = Resource(resource_name)
        if len(resource.assets) == 0:
            continue
        resource_dict[resource_name] = resource
        markets.extend(list(set(asset.market for asset in resource.assets)))
    markets = list(set(markets))

    return represented_asset_types, markets, resource_dict


def get_power_data(
    resource_dict: Dict[str, Resource]
) -> Tuple[
    Dict[str, pd.DataFrame],
    Dict[str, pd.DataFrame],
    Dict[str, float],
    Dict[str, float],
    Dict[str, float],
    Dict[str, float],
]:
    """Get power data, separating demand and supply,
    as time series per resource and as totals (summed over time) per resource and per asset.

    Getting sensor data of a Resource leads to database queries (unless results are already cached).

    :returns: a tuple comprising:
        - a dictionary of resource names (as keys) and a DataFrame with aggregated time series of supply (as values)
        - a dictionary of resource names (as keys) and a DataFrame with aggregated time series of demand (as values)
        - a dictionary of resource names (as keys) and their total supply summed over time (as values)
        - a dictionary of resource names (as keys) and their total demand summed over time (as values)
        - a dictionary of asset names (as keys) and their total supply summed over time (as values)
        - a dictionary of asset names (as keys) and their total demand summed over time (as values)
    """

    # Load power data (separate demand and supply, and group data per resource)
    supply_per_resource: Dict[
        str, pd.DataFrame
    ] = {}  # power >= 0, production/supply >= 0
    demand_per_resource: Dict[
        str, pd.DataFrame
    ] = {}  # power <= 0, consumption/demand >=0 !!!
    total_supply_per_asset: Dict[str, float] = {}
    total_demand_per_asset: Dict[str, float] = {}
    for resource_name, resource in resource_dict.items():
        if (resource.aggregate_demand.values != 0).any():
            demand_per_resource[resource_name] = simplify_index(
                resource.aggregate_demand
            )
        if (resource.aggregate_supply.values != 0).any():
            supply_per_resource[resource_name] = simplify_index(
                resource.aggregate_supply
            )
        total_supply_per_asset = {**total_supply_per_asset, **resource.total_supply}
        total_demand_per_asset = {**total_demand_per_asset, **resource.total_demand}
    total_supply_per_resource = {
        k: v.total_aggregate_supply for k, v in resource_dict.items()
    }
    total_demand_per_resource = {
        k: v.total_aggregate_demand for k, v in resource_dict.items()
    }
    return (
        supply_per_resource,
        demand_per_resource,
        total_supply_per_resource,
        total_demand_per_resource,
        total_supply_per_asset,
        total_demand_per_asset,
    )


def get_price_data(
    resource_dict: Dict[str, Resource]
) -> Tuple[Dict[str, tb.BeliefsDataFrame], Dict[str, float]]:

    # Load price data
    price_bdf_dict: Dict[str, tb.BeliefsDataFrame] = {}
    for resource_name, resource in resource_dict.items():
        price_bdf_dict = {**resource.cached_price_data, **price_bdf_dict}
    average_price_dict = {k: v["event_value"].mean() for k, v in price_bdf_dict.items()}

    # Uncomment if needed
    # revenue_per_asset_type = {k: v.aggregate_revenue for k, v in resource_dict.items()}
    # cost_per_asset_type = {k: v.aggregate_cost for k, v in resource_dict.items()}
    # profit_per_asset_type = {k: v.aggregate_profit_or_loss for k, v in resource_dict.items()}

    return price_bdf_dict, average_price_dict
