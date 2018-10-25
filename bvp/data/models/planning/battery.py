from typing import Union
from datetime import datetime, timedelta

from pandas import Series

from bvp.data.models.assets import Asset
from bvp.data.models.markets import Market, Price
from bvp.data.models.planning.solver import device_scheduler
from bvp.data.models.planning.utils import initialize_df, initialize_series


def schedule_battery(
    asset: Asset, market: Market, start: datetime, end: datetime, resolution: timedelta
) -> Union[Series, None]:
    """Schedule a battery asset based directly on the latest beliefs regarding market prices within the specified time
    window."""

    # Set up device constraints (only one device for this EMS)
    columns = ["max", "min", "derivative equals", "derivative max", "derivative min"]
    device_constraints = [initialize_df(columns, start, end, resolution)]
    device_constraints[0]["min"] = asset.min_soc_in_mwh - asset.soc_in_mwh
    device_constraints[0]["max"] = asset.max_soc_in_mwh - asset.soc_in_mwh
    device_constraints[0]["derivative min"] = asset.capacity_in_mw * -1
    device_constraints[0]["derivative max"] = asset.capacity_in_mw

    # Set up EMS constraints (no additional constraints)
    columns = ["derivative max", "derivative min"]
    ems_constraints = initialize_df(columns, start, end, resolution)

    # Set up commitments to optimise for
    commitment_quantities = [initialize_series(0, start, end, resolution)]
    prices = Price.make_query(market_name=market.name, query_window=(start, end)).all()
    if len(prices) != (end - start) / resolution:
        return None  # Todo: we might still schedule given some prices
    consumption_prices = [price.value for price in prices]
    production_prices = [price.value * -1 for price in prices]

    # Todo: convert to EUR/(deviation of commitment, which is in MW)
    commitment_downwards_deviation_price = [
        initialize_series(production_prices, start, end, resolution)
    ]
    commitment_upwards_deviation_price = [
        initialize_series(consumption_prices, start, end, resolution)
    ]

    ems_schedule, expected_costs = device_scheduler(
        device_constraints,
        ems_constraints,
        commitment_quantities,
        commitment_downwards_deviation_price,
        commitment_upwards_deviation_price,
    )
    battery_schedule = ems_schedule[0]

    return battery_schedule
