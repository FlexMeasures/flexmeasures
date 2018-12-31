from typing import Union
from datetime import datetime, timedelta

from pandas import Series
from pandas.tseries.frequencies import to_offset

from bvp.data.models.assets import Asset
from bvp.data.models.markets import Market, Price
from bvp.data.models.planning.solver import device_scheduler
from bvp.data.models.planning.utils import initialize_df, initialize_series


def schedule_battery(
    asset: Asset, market: Market, start: datetime, end: datetime, resolution: timedelta
) -> Union[Series, None]:
    """Schedule a battery asset based directly on the latest beliefs regarding market prices within the specified time
    window."""

    # Check for known prices or price forecasts, adjusting planning horizon accordingly
    prices = Price.collect(
        market.name,
        query_window=(start, end),
        resolution=to_offset(resolution).freqstr,
        create_if_empty=True,
    )
    if prices.isnull().values.all():
        return None
    start = prices.first_valid_index()
    end = prices.last_valid_index() + resolution

    # Set up commitments to optimise for
    commitment_quantities = [initialize_series(0, start, end, resolution)]

    # Todo: convert to EUR/(deviation of commitment, which is in MW)
    commitment_upwards_deviation_price = [prices.loc[start : end - resolution]["y"]]
    commitment_downwards_deviation_price = [
        prices.loc[start : end - resolution]["y"].multiply(-1)
    ]

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

    ems_schedule, expected_costs = device_scheduler(
        device_constraints,
        ems_constraints,
        commitment_quantities,
        commitment_downwards_deviation_price,
        commitment_upwards_deviation_price,
    )
    battery_schedule = ems_schedule[0]

    return battery_schedule
