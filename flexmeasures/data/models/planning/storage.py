from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Union, Dict

import pandas as pd
import numpy as np
from flask import current_app

from flexmeasures.data.models.planning import Scheduler
from flexmeasures.data.models.planning.linear_optimization import device_scheduler
from flexmeasures.data.models.planning.utils import (
    get_prices,
    add_tiny_price_slope,
    initialize_series,
    initialize_df,
    get_power_values,
    fallback_charging_policy,
)
from flexmeasures.data.schemas.scheduling.storage import StorageFlexModelSchema
from flexmeasures.data.schemas.scheduling import FlexContextSchema


class StorageScheduler(Scheduler):

    __version__ = "1"
    __author__ = "Seita"

    flex_model_schema = StorageFlexModelSchema

    def compute_schedule(
        self,
    ) -> Union[pd.Series, None]:
        """Schedule a battery or Charge Point based directly on the latest beliefs regarding market prices within the specified time window.
        For the resulting consumption schedule, consumption is defined as positive values.
        """
        if not self.config_inspected:
            self.inspect_config()

        soc_at_start = self.flex_model.get("soc_at_start")
        soc_targets = self.flex_model.get("soc_targets")
        soc_min = self.flex_model.get("soc_min")
        soc_max = self.flex_model.get("soc_max")
        roundtrip_efficiency = self.flex_model.get("roundtrip_efficiency")
        prefer_charging_sooner = self.flex_model.get("prefer_charging_sooner", True)

        consumption_price_sensor = self.flex_context.get("consumption_price_sensor")
        production_price_sensor = self.flex_context.get("production_price_sensor")
        inflexible_device_sensors = self.flex_context.get(
            "inflexible_device_sensors", []
        )

        # Check for required Sensor attributes
        self.sensor.check_required_attributes([("capacity_in_mw", (float, int))])

        # Check for known prices or price forecasts, trimming planning window accordingly
        up_deviation_prices, (start, end) = get_prices(
            (self.start, self.end),
            self.resolution,
            beliefs_before=self.belief_time,
            price_sensor=consumption_price_sensor,
            sensor=self.sensor,
            allow_trimmed_query_window=False,
        )
        down_deviation_prices, (start, end) = get_prices(
            (start, end),
            self.resolution,
            beliefs_before=self.belief_time,
            price_sensor=production_price_sensor,
            sensor=self.sensor,
            allow_trimmed_query_window=False,
        )

        start = pd.Timestamp(start).tz_convert("UTC")
        end = pd.Timestamp(end).tz_convert("UTC")

        # Add tiny price slope to prefer charging now rather than later, and discharging later rather than now.
        # We penalise the future with at most 1 per thousand times the price spread.
        if prefer_charging_sooner:
            up_deviation_prices = add_tiny_price_slope(
                up_deviation_prices, "event_value"
            )
            down_deviation_prices = add_tiny_price_slope(
                down_deviation_prices, "event_value"
            )

        # Set up commitments to optimise for
        commitment_quantities = [initialize_series(0, start, end, self.resolution)]

        # Todo: convert to EUR/(deviation of commitment, which is in MW)
        commitment_upwards_deviation_price = [
            up_deviation_prices.loc[start : end - self.resolution]["event_value"]
        ]
        commitment_downwards_deviation_price = [
            down_deviation_prices.loc[start : end - self.resolution]["event_value"]
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
        device_constraints = [
            initialize_df(columns, start, end, self.resolution)
            for i in range(1 + len(inflexible_device_sensors))
        ]
        for i, inflexible_sensor in enumerate(inflexible_device_sensors):
            device_constraints[i + 1]["derivative equals"] = get_power_values(
                query_window=(start, end),
                resolution=self.resolution,
                beliefs_before=self.belief_time,
                sensor=inflexible_sensor,
            )
        if soc_targets is not None and not soc_targets.empty:
            soc_targets = soc_targets.tz_convert("UTC")
            device_constraints[0]["equals"] = soc_targets.shift(
                -1, freq=self.resolution
            ).values * (timedelta(hours=1) / self.resolution) - soc_at_start * (
                timedelta(hours=1) / self.resolution
            )  # shift "equals" constraint for target SOC by one resolution (the target defines a state at a certain time,
            # while the "equals" constraint defines what the total stock should be at the end of a time slot,
            # where the time slot is indexed by its starting time)
        device_constraints[0]["min"] = (soc_min - soc_at_start) * (
            timedelta(hours=1) / self.resolution
        )
        device_constraints[0]["max"] = (soc_max - soc_at_start) * (
            timedelta(hours=1) / self.resolution
        )
        if self.sensor.get_attribute("is_strictly_non_positive"):
            device_constraints[0]["derivative min"] = 0
        else:
            device_constraints[0]["derivative min"] = (
                self.sensor.get_attribute("capacity_in_mw") * -1
            )
        if self.sensor.get_attribute("is_strictly_non_negative"):
            device_constraints[0]["derivative max"] = 0
        else:
            device_constraints[0]["derivative max"] = self.sensor.get_attribute(
                "capacity_in_mw"
            )

        # Apply round-trip efficiency evenly to charging and discharging
        device_constraints[0]["derivative down efficiency"] = (
            roundtrip_efficiency**0.5
        )
        device_constraints[0]["derivative up efficiency"] = roundtrip_efficiency**0.5

        # Set up EMS constraints
        columns = ["derivative max", "derivative min"]
        ems_constraints = initialize_df(columns, start, end, self.resolution)
        ems_capacity = self.sensor.generic_asset.get_attribute("capacity_in_mw")
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
                self.sensor, device_constraints[0], start, end, self.resolution
            )
        else:
            battery_schedule = ems_schedule[0]

        # Round schedule
        if self.round_to_decimals:
            battery_schedule = battery_schedule.round(self.round_to_decimals)

        return battery_schedule

    def persist_flex_model(self):
        """Store new soc info as GenericAsset attributes"""
        self.sensor.generic_asset.set_attribute("soc_datetime", self.start.isoformat())
        if self.flex_model.get("soc_unit") == "kWh":
            self.sensor.generic_asset.set_attribute(
                "soc_in_mwh", self.flex_model["soc_at_start"] / 1000
            )
        else:
            self.sensor.generic_asset.set_attribute(
                "soc_in_mwh", self.flex_model["soc_at_start"]
            )

    def inspect_flex_config(self):
        """
        Check storage flex model and fill in values from wider context, if possible.
        Mostly, we allow several fields to come from sensor attributes.
        """
        if self.flex_model is None:
            self.flex_model = {}

        # Check state of charge
        # Preferably, a starting soc is given.
        # Otherwise, we try to retrieve the current state of charge from the asset (if that is the valid one at the start).
        # If that doesn't work, we set the starting soc to 0 (some assets don't use the concept of a state of charge,
        # and without soc targets and limits the starting soc doesn't matter).
        if (
            "soc_at_start" not in self.flex_model
            or self.flex_model["soc_at_start"] is None
        ):
            if (
                self.start == self.sensor.get_attribute("soc_datetime")
                and self.sensor.get_attribute("soc_in_mwh") is not None
            ):
                self.flex_model["soc_at_start"] = self.sensor.get_attribute(
                    "soc_in_mwh"
                )
            else:
                self.flex_model["soc_at_start"] = 0

        # Check for round-trip efficiency
        if (
            "roundtrip_efficiency" not in self.flex_model
            or self.flex_model["roundtrip_efficiency"] is None
        ):
            # Get default from sensor, or use 100% otherwise
            self.flex_model["roundtrip_efficiency"] = self.sensor.get_attribute(
                "roundtrip_efficiency", 1
            )
        if (
            self.flex_model["roundtrip_efficiency"] <= 0
            or self.flex_model["roundtrip_efficiency"] > 1
        ):
            raise ValueError("roundtrip_efficiency expected within the interval (0, 1]")

        self.ensure_soc_min_max()

        # Now it's time to check if our flex configurations hold up to basic expectations
        self.flex_model = self.flex_model_schema().load(self.flex_model)
        self.flex_context = FlexContextSchema().load(self.flex_context)

        self.check_soc_min_max_and_targets()

        # Make SOC targets into a series for easier use
        self.flex_model["soc_targets"] = build_soc_targets(
            self.flex_model.get("soc_targets", []),
            self.start,
            self.end,
            self.sensor.event_resolution,
        )

        return self.flex_model

    def get_min_max_targets(self) -> tuple(float | None):
        min_target = None
        max_target = None
        if "soc_targets" in self.flex_model and len(self.flex_model["soc_targets"]) > 0:
            min_target = min(
                [target["value"] for target in self.flex_model["soc_targets"]]
            )
            max_target = max(
                [target["value"] for target in self.flex_model["soc_targets"]]
            )
        return min_target, max_target

    def get_min_max_soc_on_sensor(
        self, adjust_unit: bool = False
    ) -> tuple(float | None):
        soc_min_sensor = self.sensor.get_attribute("min_soc_in_mwh", None)
        soc_max_sensor = self.sensor.get_attribute("max_soc_in_mwh", None)
        if adjust_unit:
            if soc_min_sensor and self.flex_model.get("soc_unit") == "kWh":
                soc_min_sensor *= 1000  # later steps assume soc data is kWh
            if soc_max_sensor and self.flex_model.get("soc_unit") == "kWh":
                soc_max_sensor *= 1000
        return soc_min_sensor, soc_max_sensor

    def check_soc_min_max_and_targets(self):
        """
        Check if targets or min and max values are out of any existing known bounds
        """
        min_target, max_target = self.get_min_max_targets()
        soc_min_sensor, soc_max_sensor = self.get_min_max_soc_on_sensor()

        if min_target and min_target < 0:
            raise ValueError(f"Lowest SOC target {min_target} MWh lies below 0.")
        if (
            min_target is not None
            and soc_min_sensor is not None
            and min_target < soc_min_sensor
        ):
            raise ValueError(
                f"Target value {min_target} MWh is below sensor {self.sensor.id}'s min_soc_in_mwh attribute of {soc_min_sensor}."
            )
        if (
            self.flex_model.get("soc_min") is not None
            and self.flex_model.get("soc_min") < soc_min_sensor
        ):
            raise ValueError(
                f"Value {self.flex_model.get('soc_min')} MWh for soc_min is below sensor {self.sensor.id}'s min_soc_in_mwh attribute of {soc_min_sensor}."
            )
        if (
            max_target is not None
            and soc_max_sensor is not None
            and max_target > soc_max_sensor
        ):
            raise ValueError(
                f"Target value {max_target} MWh is above sensor {self.sensor.id}'s max_soc_in_mwh attribute of {soc_max_sensor}."
            )
        if (
            self.flex_model.get("soc_max") is not None
            and self.flex_model.get("soc_max") > soc_max_sensor
        ):
            raise ValueError(
                f"Value {self.flex_model.get('soc_max')} MWh for soc_max is above sensor {self.sensor.id}'s max_soc_in_mwh attribute of {soc_max_sensor}."
            )

    def ensure_soc_min_max(self):
        """
        Make sure we have min and max SOC.
        If not passed directly, then get default from sensor or targets.
        """
        _, max_target = self.get_min_max_targets()
        soc_min_sensor, soc_max_sensor = self.get_min_max_soc_on_sensor(
            adjust_unit=True
        )
        if "soc_min" not in self.flex_model or self.flex_model["soc_min"] is None:
            # Default is 0 - can't drain the storage by more than it contains
            self.flex_model["soc_min"] = soc_min_sensor if soc_min_sensor else 0
        if "soc_max" not in self.flex_model or self.flex_model["soc_max"] is None:
            self.flex_model["soc_max"] = soc_max_sensor
            # Lacking information about the battery's nominal capacity, we use the highest target value as the maximum state of charge
            if self.flex_model["soc_max"] is None:
                if max_target:
                    self.flex_model["soc_max"] = max_target
                else:
                    raise ValueError(
                        "Need maximal permitted state of charge, please specify soc_max or some soc_targets."
                    )


def build_soc_targets(
    targets: List[Dict[datetime, float]],
    start_of_schedule: datetime,
    end_of_schedule: datetime,
    resolution: timedelta,
) -> pd.Series:
    """
    Utility function to make sure soc targets are a convenient series fitting our time frame.
    """
    soc_targets = initialize_series(
        np.nan,
        start=start_of_schedule,
        end=end_of_schedule,
        resolution=resolution,
        inclusive="right",  # note that target values are indexed by their due date (i.e. inclusive="right")
    )

    for target in targets:
        target_value = target["value"]

        target_datetime = target["datetime"]
        target_datetime = target_datetime.astimezone(
            soc_targets.index.tzinfo
        )  # otherwise DST would be problematic
        if target_datetime > end_of_schedule:
            raise ValueError(
                f'Target datetime exceeds {end_of_schedule}. Maximum scheduling horizon is {current_app.config.get("FLEXMEASURES_PLANNING_HORIZON")}.'
            )

        soc_targets.loc[target_datetime] = target_value

    # soc targets are at the end of each time slot, while prices are indexed by the start of each time slot
    soc_targets = soc_targets[start_of_schedule + resolution : end_of_schedule]

    return soc_targets
