from typing import Union
from datetime import datetime, timedelta

from pandas import Series

from flexmeasures.data.models.assets import Asset
from flexmeasures.data.models.markets import Market
from flexmeasures.data.models.planning.solver import device_scheduler
from flexmeasures.data.models.planning.utils import (
    initialize_df,
    initialize_series,
    add_tiny_price_slope,
    get_prices,
)


def schedule_charging_station(
    asset: Asset,
    market: Market,
    start: datetime,
    end: datetime,
    resolution: timedelta,
    soc_at_start: float,
    soc_targets: Series,
    prefer_charging_sooner: bool = True,
) -> Union[Series, None]:
    """Schedule a charging station asset based directly on the latest beliefs regarding market prices within the specified time
    window.
    For the resulting consumption schedule, consumption is defined as positive values.
    Todo: handle uni-directional charging by setting the "min" or "derivative min" constraint to 0
    """

    # Check for known prices or price forecasts, trimming planning window accordingly
    prices, (start, end) = get_prices(
        market, (start, end), resolution, allow_trimmed_query_window=True
    )
    # soc targets are at the end of each time slot, while prices are indexed by the start of each time slot
    soc_targets = soc_targets[start + resolution : end]

    # Add tiny price slope to prefer charging now rather than later, and discharging later rather than now.
    # We penalise the future with at most 1 per thousand times the price spread.
    if prefer_charging_sooner:
        prices = add_tiny_price_slope(prices, "event_value")

    # Set up commitments to optimise for
    commitment_quantities = [initialize_series(0, start, end, resolution)]

    # Todo: convert to EUR/(deviation of commitment, which is in MW)
    commitment_upwards_deviation_price = [
        prices.loc[start : end - resolution]["event_value"]
    ]
    commitment_downwards_deviation_price = [
        prices.loc[start : end - resolution]["event_value"]
    ]

    # Set up device constraints (only one device for this EMS)
    columns = [
        "equals",
        "max",
        "min",
        "derivative equals",
        "derivative max",
        "derivative min",
    ]
    device_constraints = [initialize_df(columns, start, end, resolution)]
    device_constraints[0]["equals"] = soc_targets.shift(-1, freq=resolution).values * (
        timedelta(hours=1) / resolution
    ) - soc_at_start * (
        timedelta(hours=1) / resolution
    )  # shift "equals" constraint for target SOC by one resolution (the target defines a state at a certain time,
    # while the "equals" constraint defines what the total stock should be at the end of a time slot,
    # where the time slot is indexed by its starting time)
    device_constraints[0]["min"] = -soc_at_start * (
        timedelta(hours=1) / resolution
    )  # Can't drain the EV battery by more than it contains
    device_constraints[0]["max"] = max(soc_targets.values) * (
        timedelta(hours=1) / resolution
    ) - soc_at_start * (
        timedelta(hours=1) / resolution
    )  # Lacking information about the battery's nominal capacity, we use the highest target value as the maximum state of charge
    if asset.is_pure_consumer:
        device_constraints[0]["derivative min"] = 0
    else:
        device_constraints[0]["derivative min"] = asset.capacity_in_mw * -1
    if asset.is_pure_producer:
        device_constraints[0]["derivative max"] = 0
    else:
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
    charging_station_schedule = ems_schedule[0]

    return charging_station_schedule
