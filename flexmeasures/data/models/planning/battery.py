from typing import List, Optional, Union
from datetime import datetime, timedelta

import pandas as pd

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.planning.solver import device_scheduler
from flexmeasures.data.models.planning.utils import (
    initialize_df,
    initialize_series,
    add_tiny_price_slope,
    get_prices,
    get_power_values,
    fallback_charging_policy,
)


def schedule_battery(
    sensor: Sensor,
    start: datetime,
    end: datetime,
    resolution: timedelta,
    soc_at_start: float,
    soc_targets: Optional[pd.Series] = None,
    soc_min: Optional[float] = None,
    soc_max: Optional[float] = None,
    roundtrip_efficiency: Optional[float] = None,
    prefer_charging_sooner: bool = True,
    consumption_price_sensor: Optional[Sensor] = None,
    production_price_sensor: Optional[Sensor] = None,
    inflexible_device_sensors: Optional[List[Sensor]] = None,
    belief_time: Optional[datetime] = None,
    round_to_decimals: Optional[int] = 6,
) -> Union[pd.Series, None]:
    """Schedule a battery asset based directly on the latest beliefs regarding market prices within the specified time
    window.
    For the resulting consumption schedule, consumption is defined as positive values.
    """

    # Check for required Sensor attributes
    sensor.check_required_attributes(
        [
            ("capacity_in_mw", (float, int)),
            ("max_soc_in_mwh", (float, int)),
            ("min_soc_in_mwh", (float, int)),
        ],
    )

    # Check for round-trip efficiency
    if roundtrip_efficiency is None:
        # Get default from sensor, or use 100% otherwise
        roundtrip_efficiency = sensor.get_attribute("roundtrip_efficiency", 1)
    if roundtrip_efficiency <= 0 or roundtrip_efficiency > 1:
        raise ValueError("roundtrip_efficiency expected within the interval (0, 1]")

    # Check for min and max SOC, or get default from sensor
    if soc_min is None:
        soc_min = sensor.get_attribute("min_soc_in_mwh")
    if soc_max is None:
        soc_max = sensor.get_attribute("max_soc_in_mwh")

    # Check for known prices or price forecasts, trimming planning window accordingly
    up_deviation_prices, (start, end) = get_prices(
        (start, end),
        resolution,
        beliefs_before=belief_time,
        price_sensor=consumption_price_sensor,
        sensor=sensor,
        allow_trimmed_query_window=True,
    )
    down_deviation_prices, (start, end) = get_prices(
        (start, end),
        resolution,
        beliefs_before=belief_time,
        price_sensor=production_price_sensor,
        sensor=sensor,
        allow_trimmed_query_window=True,
    )

    start = pd.Timestamp(start).tz_convert("UTC")
    end = pd.Timestamp(end).tz_convert("UTC")
    if soc_targets is not None:
        # soc targets are at the end of each time slot, while prices are indexed by the start of each time slot
        soc_targets = soc_targets.tz_convert("UTC")
        soc_targets = soc_targets[start + resolution : end]

    # Add tiny price slope to prefer charging now rather than later, and discharging later rather than now.
    # We penalise the future with at most 1 per thousand times the price spread.
    if prefer_charging_sooner:
        up_deviation_prices = add_tiny_price_slope(up_deviation_prices, "event_value")
        down_deviation_prices = add_tiny_price_slope(
            down_deviation_prices, "event_value"
        )

    # Set up commitments to optimise for
    commitment_quantities = [initialize_series(0, start, end, resolution)]

    # Todo: convert to EUR/(deviation of commitment, which is in MW)
    commitment_upwards_deviation_price = [
        up_deviation_prices.loc[start : end - resolution]["event_value"]
    ]
    commitment_downwards_deviation_price = [
        down_deviation_prices.loc[start : end - resolution]["event_value"]
    ]

    # Set up device constraints: only one scheduled flexible device for this EMS (at index 0), plus the forecasted inflexible devices (at indices 1 to n).
    columns = [
        "equals",
        "max",
        "min",
        "derivative equals",
        "derivative max",
        "derivative min",
        "derivative down efficiency",
        "derivative up efficiency",
    ]
    if inflexible_device_sensors is None:
        inflexible_device_sensors = []
    device_constraints = [
        initialize_df(columns, start, end, resolution)
        for i in range(1 + len(inflexible_device_sensors))
    ]
    for i, inflexible_sensor in enumerate(inflexible_device_sensors):
        device_constraints[i + 1]["derivative equals"] = get_power_values(
            query_window=(start, end),
            resolution=resolution,
            beliefs_before=belief_time,
            sensor=inflexible_sensor,
        )
    if soc_targets is not None:
        device_constraints[0]["equals"] = soc_targets.shift(
            -1, freq=resolution
        ).values * (timedelta(hours=1) / resolution) - soc_at_start * (
            timedelta(hours=1) / resolution
        )  # shift "equals" constraint for target SOC by one resolution (the target defines a state at a certain time,
        # while the "equals" constraint defines what the total stock should be at the end of a time slot,
        # where the time slot is indexed by its starting time)
    device_constraints[0]["min"] = (soc_min - soc_at_start) * (
        timedelta(hours=1) / resolution
    )
    device_constraints[0]["max"] = (soc_max - soc_at_start) * (
        timedelta(hours=1) / resolution
    )
    device_constraints[0]["derivative min"] = (
        sensor.get_attribute("capacity_in_mw") * -1
    )
    device_constraints[0]["derivative max"] = sensor.get_attribute("capacity_in_mw")

    # Apply round-trip efficiency evenly to charging and discharging
    device_constraints[0]["derivative down efficiency"] = roundtrip_efficiency**0.5
    device_constraints[0]["derivative up efficiency"] = roundtrip_efficiency**0.5

    # Set up EMS constraints
    columns = ["derivative max", "derivative min"]
    ems_constraints = initialize_df(columns, start, end, resolution)
    ems_capacity = sensor.generic_asset.get_attribute("capacity_in_mw")
    if ems_capacity is not None:
        ems_constraints["derivative min"] = ems_capacity * -1
        ems_constraints["derivative max"] = ems_capacity

    ems_schedule, expected_costs, scheduler_results = device_scheduler(
        device_constraints,
        ems_constraints,
        commitment_quantities,
        commitment_downwards_deviation_price,
        commitment_upwards_deviation_price,
    )
    if scheduler_results.solver.termination_condition == "infeasible":
        # Fallback policy if the problem was unsolvable
        battery_schedule = fallback_charging_policy(
            sensor, device_constraints[0], start, end, resolution
        )
    else:
        battery_schedule = ems_schedule[0]

    # Round schedule
    if round_to_decimals:
        battery_schedule = battery_schedule.round(round_to_decimals)

    return battery_schedule
