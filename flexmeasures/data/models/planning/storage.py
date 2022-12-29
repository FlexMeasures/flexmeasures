from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Dict

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

    def compute_schedule(
        self,
    ) -> pd.Series | None:
        """Schedule a battery or Charge Point based directly on the latest beliefs regarding market prices within the specified time window.
        For the resulting consumption schedule, consumption is defined as positive values.
        """
        if not self.config_deserialized:
            self.deserialize_config()

        start = self.start
        end = self.end
        resolution = self.resolution
        belief_time = self.belief_time
        sensor = self.sensor
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
            (start, end),
            resolution,
            beliefs_before=belief_time,
            price_sensor=consumption_price_sensor,
            sensor=sensor,
            allow_trimmed_query_window=False,
        )
        down_deviation_prices, (start, end) = get_prices(
            (start, end),
            resolution,
            beliefs_before=belief_time,
            price_sensor=production_price_sensor,
            sensor=sensor,
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
            # make an equality series with the SOC targets set in the flex model
            # device_constraints[0] refers to the flexible device we are scheduling
            device_constraints[0]["equals"] = build_device_soc_targets(
                soc_targets,
                soc_at_start,
                start,
                end,
                resolution,
            )

        device_constraints[0]["min"] = (soc_min - soc_at_start) * (
            timedelta(hours=1) / resolution
        )
        device_constraints[0]["max"] = (soc_max - soc_at_start) * (
            timedelta(hours=1) / resolution
        )
        if sensor.get_attribute("is_strictly_non_positive"):
            device_constraints[0]["derivative min"] = 0
        else:
            device_constraints[0]["derivative min"] = (
                sensor.get_attribute("capacity_in_mw") * -1
            )
        if sensor.get_attribute("is_strictly_non_negative"):
            device_constraints[0]["derivative max"] = 0
        else:
            device_constraints[0]["derivative max"] = sensor.get_attribute(
                "capacity_in_mw"
            )

        # Apply round-trip efficiency evenly to charging and discharging
        device_constraints[0]["derivative down efficiency"] = (
            roundtrip_efficiency**0.5
        )
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

    def deserialize_flex_config(self):
        """
        Deserialize storage flex model and the flex context against schemas.
        Before that, we fill in values from wider context, if possible.
        Mostly, we allow several fields to come from sensor attributes.

        Note: Before we apply the flex config schemas, we need to use the flex config identifiers with hyphens,
              (this is how they are represented to outside, e.g. by the API), after deserialization
              we use internal schema names (with underscores).
        """
        if self.flex_model is None:
            self.flex_model = {}

        # Check state of charge.
        # Preferably, a starting soc is given.
        # Otherwise, we try to retrieve the current state of charge from the asset (if that is the valid one at the start).
        # If that doesn't work, we set the starting soc to 0 (some assets don't use the concept of a state of charge,
        # and without soc targets and limits the starting soc doesn't matter).
        if (
            "soc-at-start" not in self.flex_model
            or self.flex_model["soc-at-start"] is None
        ):
            if (
                self.start == self.sensor.get_attribute("soc_datetime")
                and self.sensor.get_attribute("soc_in_mwh") is not None
            ):
                self.flex_model["soc-at-start"] = self.sensor.get_attribute(
                    "soc_in_mwh"
                )
            else:
                self.flex_model["soc-at-start"] = 0

        # Check for round-trip efficiency
        if (
            "roundtrip-efficiency" not in self.flex_model
            or self.flex_model["roundtrip-efficiency"] is None
        ):
            # Get default from sensor, or use 100% otherwise
            self.flex_model["roundtrip-efficiency"] = self.sensor.get_attribute(
                "roundtrip_efficiency", 1
            )
        if (
            self.flex_model["roundtrip-efficiency"] <= 0
            or self.flex_model["roundtrip-efficiency"] > 1
        ):
            raise ValueError("roundtrip efficiency expected within the interval (0, 1]")

        self.ensure_soc_min_max()

        # Now it's time to check if our flex configurations holds up to schemas
        self.flex_model = StorageFlexModelSchema().load(self.flex_model)
        self.flex_context = FlexContextSchema().load(self.flex_context)

        return self.flex_model

    def get_min_max_targets(
        self, deserialized_names: bool = True
    ) -> tuple[float | None, float | None]:
        min_target = None
        max_target = None
        soc_targets_label = "soc_targets" if deserialized_names else "soc-targets"
        if (
            soc_targets_label in self.flex_model
            and len(self.flex_model[soc_targets_label]) > 0
        ):
            min_target = min(
                [target["value"] for target in self.flex_model[soc_targets_label]]
            )
            max_target = max(
                [target["value"] for target in self.flex_model[soc_targets_label]]
            )
        return min_target, max_target

    def get_min_max_soc_on_sensor(
        self, adjust_unit: bool = False, deserialized_names: bool = True
    ) -> tuple[float | None]:
        soc_min_sensor = self.sensor.get_attribute("min_soc_in_mwh", None)
        soc_max_sensor = self.sensor.get_attribute("max_soc_in_mwh", None)
        soc_unit_label = "soc_unit" if deserialized_names else "soc-unit"
        if adjust_unit:
            if soc_min_sensor and self.flex_model.get(soc_unit_label) == "kWh":
                soc_min_sensor *= 1000  # later steps assume soc data is kWh
            if soc_max_sensor and self.flex_model.get(soc_unit_label) == "kWh":
                soc_max_sensor *= 1000
        return soc_min_sensor, soc_max_sensor

    def ensure_soc_min_max(self):
        """
        Make sure we have min and max SOC.
        If not passed directly, then get default from sensor or targets.
        """
        _, max_target = self.get_min_max_targets(deserialized_names=False)
        soc_min_sensor, soc_max_sensor = self.get_min_max_soc_on_sensor(
            adjust_unit=True, deserialized_names=False
        )
        if "soc-min" not in self.flex_model or self.flex_model["soc-min"] is None:
            # Default is 0 - can't drain the storage by more than it contains
            self.flex_model["soc-min"] = soc_min_sensor if soc_min_sensor else 0
        if "soc-max" not in self.flex_model or self.flex_model["soc-max"] is None:
            self.flex_model["soc-max"] = soc_max_sensor
            # Lacking information about the battery's nominal capacity, we use the highest target value as the maximum state of charge
            if self.flex_model["soc-max"] is None:
                if max_target:
                    self.flex_model["soc-max"] = max_target
                else:
                    raise ValueError(
                        "Need maximal permitted state of charge, please specify soc-max or some soc-targets."
                    )


def build_device_soc_targets(
    targets: List[Dict[datetime, float]] | pd.Series,
    soc_at_start: float,
    start_of_schedule: datetime,
    end_of_schedule: datetime,
    resolution: timedelta,
) -> pd.Series:
    """
    Utility function to create a Pandas series from SOC targets we got from the flex-model.

    Should set NaN anywhere where there is no target.

    Target SOC values should be indexed by their due date. For example, for quarter-hourly targets between 5 and 6 AM:
    >>> df = pd.Series(data=[1, 2, 2.5, 3], index=pd.date_range(datetime(2010,1,1,5), datetime(2010,1,1,6), freq=timedelta(minutes=15), inclusive="right"))
    >>> print(df)
        2010-01-01 05:15:00    1.0
        2010-01-01 05:30:00    2.0
        2010-01-01 05:45:00    2.5
        2010-01-01 06:00:00    3.0
        Freq: 15T, dtype: float64

    TODO: this function could become the deserialization method of a new SOCTargetsSchema (targets, plural), which wraps SOCTargetSchema.

    """
    if isinstance(targets, pd.Series):  # some teats prepare it this way
        device_targets = targets
    else:
        device_targets = initialize_series(
            np.nan,
            start=start_of_schedule,
            end=end_of_schedule,
            resolution=resolution,
            inclusive="right",  # note that target values are indexed by their due date (i.e. inclusive="right")
        )

        for target in targets:
            target_value = target["value"]
            target_datetime = target["datetime"].astimezone(
                device_targets.index.tzinfo
            )  # otherwise DST would be problematic
            if target_datetime > end_of_schedule:
                raise ValueError(
                    f'Target datetime exceeds {end_of_schedule}. Maximum scheduling horizon is {current_app.config.get("FLEXMEASURES_PLANNING_HORIZON")}.'
                )

            device_targets.loc[target_datetime] = target_value

        # soc targets are at the end of each time slot, while prices are indexed by the start of each time slot
        device_targets = device_targets[
            start_of_schedule + resolution : end_of_schedule
        ]

    device_targets = device_targets.tz_convert("UTC")

    # shift "equals" constraint for target SOC by one resolution (the target defines a state at a certain time,
    # while the "equals" constraint defines what the total stock should be at the end of a time slot,
    # where the time slot is indexed by its starting time)
    device_targets = device_targets.shift(-1, freq=resolution).values * (
        timedelta(hours=1) / resolution
    ) - soc_at_start * (timedelta(hours=1) / resolution)

    return device_targets
