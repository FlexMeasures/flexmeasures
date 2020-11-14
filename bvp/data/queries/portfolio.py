from typing import Dict, List

from datetime import datetime

from bvp.data.models.assets import Asset, Power
from bvp.data.models.markets import Price
from bvp.data.queries.utils import simplify_index
from bvp.data.services.resources import Resource


def get_structure(assets: List[Asset]):

    # Set up a resource name for each asset type
    represented_asset_types = {
        asset_type.plural_name: asset_type
        for asset_type in [asset.asset_type for asset in assets]
    }

    # Load structure (and set up resources)
    resource_dict = {}
    markets = []
    for resource_name in represented_asset_types.keys():
        resource = Resource(resource_name)
        if len(resource.assets) == 0:
            continue
        resource_dict[resource_name] = resource
        markets.extend(set(asset.market for asset in resource.assets))
    markets = set(markets)

    return represented_asset_types, markets, resource_dict


def get_power_data(
    start: datetime, end: datetime, resolution: str, resource_dict: Dict[str, Resource]
):

    # Load power data (separate demand and supply, and group data per resource)
    supply_resources_df_dict = {}  # power >= 0, production/supply >= 0
    demand_resources_df_dict = {}  # power <= 0, consumption/demand >=0 !!!
    production_per_asset = {}
    consumption_per_asset = {}
    for resource_name, resource in resource_dict.items():
        resource.get_sensor_data(
            sensor_type=Power,
            start=start,
            end=end,
            resolution=resolution,
            sum_multiple=False,
        )  # The resource caches the results
        if (resource.aggregate_demand.values != 0).any():
            demand_resources_df_dict[resource_name] = simplify_index(
                resource.aggregate_demand
            )
        if (resource.aggregate_supply.values != 0).any():
            supply_resources_df_dict[resource_name] = simplify_index(
                resource.aggregate_supply
            )
        production_per_asset = {**production_per_asset, **resource.total_supply}
        consumption_per_asset = {**consumption_per_asset, **resource.total_demand}
    production_per_asset_type = {
        k: v.total_aggregate_supply for k, v in resource_dict.items()
    }
    consumption_per_asset_type = {
        k: v.total_aggregate_demand for k, v in resource_dict.items()
    }
    return (
        supply_resources_df_dict,
        demand_resources_df_dict,
        production_per_asset_type,
        consumption_per_asset_type,
        production_per_asset,
        consumption_per_asset,
    )


def get_price_data(
    start: datetime, end: datetime, resolution: str, resource_dict: Dict[str, Resource]
):

    # Load price data
    price_bdf_dict = {}
    for resource_name, resource in resource_dict.items():
        price_bdf_dict = resource.get_sensor_data(
            sensor_type=Price,
            sensor_key_attribute="market.name",
            start=start,
            end=end,
            resolution=resolution,
            sum_multiple=False,
            prior_data=price_bdf_dict,
            clear_cached_data=False,
        )
    average_price_dict = {k: v["event_value"].mean() for k, v in price_bdf_dict.items()}

    # Uncomment if needed
    # revenue_per_asset_type = {k: v.aggregate_revenue for k, v in resource_dict.items()}
    # cost_per_asset_type = {k: v.aggregate_cost for k, v in resource_dict.items()}
    # profit_per_asset_type = {k: v.aggregate_profit_or_loss for k, v in resource_dict.items()}

    return price_bdf_dict, average_price_dict
