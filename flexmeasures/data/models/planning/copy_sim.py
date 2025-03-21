from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import time

from flexmeasures.data.models.planning.linear_optimization import device_scheduler
from flexmeasures.data.models.planning.utils import initialize_series, initialize_df

from flexmeasures.data.models.planning import (
    FlowCommitment,
    Scheduler,
    SchedulerOutputType,
    StockCommitment,
)

from flexmeasures.data.models.planning.storage import StorageScheduler

from pyomo.environ import value

TOLERANCE = 0.00001

from flexmeasures.app import create

import warnings
warnings.filterwarnings('ignore')

app = create()


def run_simultaneous_scheduler_with_params_1day(
    start, end, resolution,
    soc_max, soc_min,
    soc_at_start, target_value,
    start_datetime, target_datetime,
    device_capacity_max, device_capacity_min,
    ems_capacity_max, ems_capacity_min,
    market_prices, soc_target_penalty
):
    """
    Parameters:
    - start (Timestamp): Start time for the schedule.
    - end (Timestamp): End time for the schedule.
    - resolution (timedelta): Time resolution for scheduling.
    - soc_max (list): Maximum SoC for each device.
    - soc_min (list): Minimum SoC for each device.
    - soc_at_start (list): Initial state of charge (SoC) for each device.
    - target_value (list): Target SoC for each device.
    - start_datetime (list): Start times for charging for each device.
    - target_datetime (list): Target times for charging for each device.
    - device_capacity_max (float): Maximum device capacity (charging).
    - device_capacity_min (float): Minimum device capacity (discharging).
    - ems_capacity_max (float): Maximum EMS capacity (charging).
    - ems_capacity_min (float): Minimum EMS capacity (discharging).
    - market_prices (list): Hourly market prices for the entire period.
    - soc_target_penalty (float): Penalty for unmet target SoC.
    """

    def initialize_combined_constraints(
        num_devices, soc_at_start, soc_max, soc_min, target_datetime, target_value, start_datetime
    ):
        device_constraints = []
        for i in range(num_devices):
            constraints = initialize_df(StorageScheduler.COLUMNS, start, end, resolution)

            start_time = pd.Timestamp(start_datetime[i]) - timedelta(hours=1)
            target_time = pd.Timestamp(target_datetime[i])

            constraints["max"] = soc_max[i] - soc_at_start[i]
            constraints["min"] = soc_min[i] - soc_at_start[i]
            constraints["derivative max"] = device_capacity_max
            constraints["derivative min"] = device_capacity_min

            constraints.loc[:start_time, ["max", "min", "derivative max", "derivative min"]] = 0
            constraints.loc[target_time + resolution:, ["derivative max", "derivative min"]] = 0

            constraints.loc[target_time, "max"] = target_value[i] - soc_at_start[i]
            constraints.loc[target_time + resolution:, ["max", "min"]] = constraints.loc[target_time, ["max", "min"]].values

            device_constraints.append(constraints)

        return device_constraints

    def initialize_combined_commitments(num_devices):
        commitments = []

        # Energy commitments (market price flexibility)
        for _ in range(num_devices):
            energy_commitment = initialize_df(
                ["quantity", "downwards deviation price", "upwards deviation price", "group"],
                start, end, resolution
            )
            energy_commitment["quantity"] = 0
            energy_commitment["downwards deviation price"] = market_prices
            energy_commitment["upwards deviation price"] = market_prices
            energy_commitment["group"] = list(range(len(energy_commitment)))
            commitments.append(energy_commitment)

        # Stock commitments (soft target enforcement)
        for i in range(num_devices):
            stock_commitment = initialize_df(
                ["quantity", "downwards deviation price", "upwards deviation price", "group"],
                start, end, resolution
            )
            stock_commitment.loc[pd.Timestamp(target_datetime[i]), "quantity"] = target_value[i] - soc_at_start[i]
            stock_commitment.loc[pd.Timestamp(target_datetime[i]), "downwards deviation price"] = -soc_target_penalty
            stock_commitment.loc[pd.Timestamp(target_datetime[i]), "upwards deviation price"] = soc_target_penalty
            #stock_commitment["upwards deviation price"] = 0
            # stock_commitment.loc[pd.Timestamp(target_datetime[i]), "upwards deviation price"] = soc_target_penalty
            stock_commitment["group"] = list(range(len(stock_commitment)))
            stock_commitment["device"] = i
            stock_commitment["class"] = StockCommitment

            commitments.append(stock_commitment)

        return commitments

    with app.app_context():
        num_devices = len(soc_at_start)
        device_constraints = initialize_combined_constraints(
            num_devices, soc_at_start, soc_max, soc_min, target_datetime, target_value, start_datetime
        )
        commitments = initialize_combined_commitments(num_devices)

        ems_constraints = initialize_df(StorageScheduler.COLUMNS, start, end, resolution)
        ems_constraints["derivative max"] = ems_capacity_max
        ems_constraints["derivative min"] = ems_capacity_min

        initial_stocks = soc_at_start
        _, _, results, model = device_scheduler(
            device_constraints, ems_constraints, commitments=commitments, initial_stock=initial_stocks
        )

        all_schedules, individual_costs, unmet_targets, daily_unmet_demand = [], [], [], 0
        for i in range(num_devices):
            schedule = initialize_series(
                data=[model.ems_power[i, j].value for j in model.j],
                start=start, end=end, resolution=resolution
            )
            all_schedules.append(schedule)

            costs = sum(schedule[j] * market_prices[j] for j in range(len(market_prices)))
            individual_costs.append((i, costs))

            # final SoC and check if target is unmet
            final_soc = initial_stocks[i] + sum(schedule)
            if final_soc < target_value[i]:
                unmet_demand = target_value[i] - final_soc
                unmet_targets.append((i, final_soc))
                daily_unmet_demand += unmet_demand

        total_costs = sum(cost for _, cost in individual_costs)

        # OUTPUT
        schedules_df = pd.DataFrame(all_schedules).transpose()
        schedules_df.columns = [f"Device {i+1}" for i in range(len(all_schedules))]
        schedules_df.index = [start + timedelta(hours=i) for i in range(len(schedules_df))]
        schedules_df = schedules_df.applymap(lambda x: 0.0 if x == -0.0 else x)

        combined_schedule = schedules_df.sum(axis=1)
        schedules_df['Combined'] = combined_schedule

        costs = [cost for _, cost in individual_costs]
        schedules_df.loc['Costs (Currency Units)'] = [f"{cost:.2f}" for cost in costs] + [f"{sum(costs):.2f}"]

        print("\n=== Power Schedules and Costs ===")
        print("Schedule shows power (kW) for each device.")
        print(schedules_df)

        if unmet_targets:
            print("\n=== Devices with Unmet Target SoC ===")
            for device_id, final_soc in unmet_targets:
                unmet_demand = target_value[device_id] - final_soc
                print(f"Device {device_id+1}: Final SoC = {final_soc:.2f}, Target SoC = {target_value[device_id]}, Unmet Demand = {unmet_demand:.2f}")
            print(f"Daily Unmet Demand: {daily_unmet_demand:.2f}")
        else:
            print("\nAll devices reached their target SoC.")

        print(commitments)
        breakpoint()
        return schedules_df




# Define Parameters for the Case
params = {
    "start": pd.Timestamp("2023-01-01 00:00:00"),
    "end": pd.Timestamp("2023-01-02 00:00:00"),
    "resolution": timedelta(hours=1),

    # State of Charge Parameters
    "soc_max": [11] * 16,
    "soc_min": [0] * 16,
    "soc_at_start": [3, 2, 5, 4] * 4,
    "target_value": [10] * 16,

    # Timing Parameters
    "start_datetime": ["2023-01-01 09:00:00"] * 16,
    "target_datetime": ["2023-01-01 13:00:00", "2023-01-01 17:00:00", "2023-01-01 14:00:00", "2023-01-01 16:00:00"] * 4,

    # Device Capacity Parameters
    "device_capacity_max": 11, # constraints["derivative max"]
    "device_capacity_min": 0,

    # EMS Capacity Parameters
    "ems_capacity_max": 11, # ems_constraints["derivative max"]
    "ems_capacity_min": 0,

    # Market and Penalty Parameters
    "market_prices": [
        0.8598, 1.4613, 2430.3887, 3000.1779, 18.6619, 369.3274, 169.8719, 174.2279, 174.2279, 174.2279,
        175.4258, 1.5697, 174.2763, 174.2279, 175.2564, 202.6992, 218.4413, 229.9242, 295.1069, 240.7174,
        249.2479, 238.2732, 229.8395, 216.5779
    ],
    "soc_target_penalty": 10000
}


sim_results_1day = run_simultaneous_scheduler_with_params_1day(**params)

print(sim_results_1day)