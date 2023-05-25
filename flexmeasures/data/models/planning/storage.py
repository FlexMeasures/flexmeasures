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
from flexmeasures.utils.time_utils import get_max_planning_horizon
from flexmeasures.utils.coding_utils import deprecated


class StorageScheduler(Scheduler):

    __version__ = "1"
    __author__ = "Seita"

    COLUMNS = [
        "equals",
        "max",
        "min",
        "derivative equals",
        "derivative max",
        "derivative min",
        "derivative down efficiency",
        "derivative up efficiency",
    ]

    def compute_schedule(self) -> pd.Series | None:
        """Schedule a battery or Charge Point based directly on the latest beliefs regarding market prices within the specified time window.
        For the resulting consumption schedule, consumption is defined as positive values.

        Deprecated method in v0.14. As an alternative, use StorageScheduler.compute().
        """

        return self.compute()

    def compute(self, skip_validation: bool = False) -> pd.Series | None:
        """Schedule a battery or Charge Point based directly on the latest beliefs regarding market prices within the specified time window.
        For the resulting consumption schedule, consumption is defined as positive values.

        :param skip_validation: If True, skip validation of constraints specified in the data.
        :returns:               The computed schedule.
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
        soc_minima = self.flex_model.get("soc_minima")
        soc_maxima = self.flex_model.get("soc_maxima")
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
        device_constraints = [
            initialize_df(StorageScheduler.COLUMNS, start, end, resolution)
            for i in range(1 + len(inflexible_device_sensors))
        ]
        for i, inflexible_sensor in enumerate(inflexible_device_sensors):
            device_constraints[i + 1]["derivative equals"] = get_power_values(
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                sensor=inflexible_sensor,
            )

        device_constraints[0] = add_storage_constraints(
            start,
            end,
            resolution,
            soc_at_start,
            soc_targets,
            soc_maxima,
            soc_minima,
            soc_max,
            soc_min,
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

        # check that storage constraints are fulfilled
        if not skip_validation:
            constraint_violations = validate_storage_constraints(
                constraints=device_constraints[0],
                soc_at_start=soc_at_start,
                min_soc=soc_min,
                soc_max=soc_max,
                resolution=resolution,
            )

            if len(constraint_violations) > 0:
                # TODO: include hints from constraint_violations into the error message
                raise ValueError("The input data yields an infeasible problem.")

        # Set up EMS constraints
        ems_constraints = initialize_df(
            StorageScheduler.COLUMNS, start, end, resolution
        )
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
        soc_unit = self.flex_model.get("soc_unit")
        if soc_unit == "kWh":
            self.sensor.generic_asset.set_attribute(
                "soc_in_mwh", self.flex_model["soc_at_start"] / 1000
            )
        elif soc_unit == "MWh":
            self.sensor.generic_asset.set_attribute(
                "soc_in_mwh", self.flex_model["soc_at_start"]
            )
        else:
            raise NotImplementedError(f"Unsupported SoC unit '{soc_unit}'.")

    def deserialize_flex_config(self):
        """
        Deserialize storage flex model and the flex context against schemas.
        Before that, we fill in values from wider context, if possible.
        Mostly, we allow several fields to come from sensor attributes.
        TODO: this work could maybe go to the schema as a pre-load hook (if we pass in the sensor to schema initialization)

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
        # soc-unit
        if "soc-unit" not in self.flex_model or self.flex_model["soc-unit"] is None:
            if self.sensor.unit in ("MWh", "kWh"):
                self.flex_model["soc-unit"] = self.sensor.unit
            elif self.sensor.unit in ("MW", "kW"):
                self.flex_model["soc-unit"] = self.sensor.unit + "h"

        # Check for round-trip efficiency
        if (
            "roundtrip-efficiency" not in self.flex_model
            or self.flex_model["roundtrip-efficiency"] is None
        ):
            # Get default from sensor, or use 100% otherwise
            self.flex_model["roundtrip-efficiency"] = self.sensor.get_attribute(
                "roundtrip_efficiency", 1
            )
        self.ensure_soc_min_max()

        # Now it's time to check if our flex configurations holds up to schemas
        self.flex_model = StorageFlexModelSchema(
            start=self.start, sensor=self.sensor
        ).load(self.flex_model)
        self.flex_context = FlexContextSchema().load(self.flex_context)

        # Extend schedule period in case a target exceeds its end
        self.possibly_extend_end()

        return self.flex_model

    def possibly_extend_end(self):
        """Extend schedule period in case a target exceeds its end.

        The schedule's duration is possibly limited by the server config setting 'FLEXMEASURES_MAX_PLANNING_HORIZON'.

        todo: when deserialize_flex_config becomes a single schema for the whole scheduler,
              this function would become a class method with a @post_load decorator.
        """
        soc_targets = self.flex_model.get("soc_targets")
        if soc_targets:
            max_target_datetime = max(
                [soc_target["datetime"] for soc_target in soc_targets]
            )
            if max_target_datetime > self.end:
                max_server_horizon = get_max_planning_horizon(self.resolution)
                if max_server_horizon:
                    self.end = min(max_target_datetime, self.start + max_server_horizon)
                else:
                    self.end = max_target_datetime

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
    ) -> tuple[float | None, float | None]:
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


def build_device_soc_values(
    soc_values: List[Dict[str, datetime | float]] | pd.Series,
    soc_at_start: float,
    start_of_schedule: datetime,
    end_of_schedule: datetime,
    resolution: timedelta,
) -> pd.Series:
    """
    Utility function to create a Pandas series from SOC values we got from the flex-model.

    Should set NaN anywhere where there is no target.

    SOC values should be indexed by their due date. For example, for quarter-hourly targets between 5 and 6 AM:
    >>> df = pd.Series(data=[1, 2, 2.5, 3], index=pd.date_range(datetime(2010,1,1,5), datetime(2010,1,1,6), freq=timedelta(minutes=15), inclusive="right"))
    >>> print(df)
        2010-01-01 05:15:00    1.0
        2010-01-01 05:30:00    2.0
        2010-01-01 05:45:00    2.5
        2010-01-01 06:00:00    3.0
        Freq: 15T, dtype: float64

    TODO: this function could become the deserialization method of a new SOCValueSchema (targets, plural), which wraps SOCValueSchema.

    """
    if isinstance(soc_values, pd.Series):  # some tests prepare it this way
        device_values = soc_values
    else:
        device_values = initialize_series(
            np.nan,
            start=start_of_schedule,
            end=end_of_schedule,
            resolution=resolution,
            inclusive="right",  # note that target values are indexed by their due date (i.e. inclusive="right")
        )

        for soc_value in soc_values:
            soc = soc_value["value"]
            soc_datetime = soc_value["datetime"].astimezone(
                device_values.index.tzinfo
            )  # otherwise DST would be problematic
            if soc_datetime > end_of_schedule:
                # Skip too-far-into-the-future target
                max_server_horizon = get_max_planning_horizon(resolution)
                current_app.logger.warning(
                    f"Disregarding target datetime {soc_datetime}, because it exceeds {end_of_schedule}. Maximum scheduling horizon is {max_server_horizon}."
                )
                continue

            device_values.loc[soc_datetime] = soc

        # soc_values are at the end of each time slot, while prices are indexed by the start of each time slot
        device_values = device_values[start_of_schedule + resolution : end_of_schedule]

    device_values = device_values.tz_convert("UTC")

    # shift "equals" constraint for target SOC by one resolution (the target defines a state at a certain time,
    # while the "equals" constraint defines what the total stock should be at the end of a time slot,
    # where the time slot is indexed by its starting time)
    device_values = device_values.shift(-1, freq=resolution).values * (
        timedelta(hours=1) / resolution
    ) - soc_at_start * (timedelta(hours=1) / resolution)

    return device_values


def add_storage_constraints(
    start: datetime,
    end: datetime,
    resolution: timedelta,
    soc_at_start: float,
    soc_targets: List[Dict[str, datetime | float]] | pd.Series | None,
    soc_maxima: List[Dict[str, datetime | float]] | pd.Series | None,
    soc_minima: List[Dict[str, datetime | float]] | pd.Series | None,
    soc_max: float,
    soc_min: float,
) -> pd.DataFrame:
    """Collect all constraints for a given storage device in a DataFrame that the device_scheduler can interpret.

    :param start:                       Start of the schedule.
    :param end:                         End of the schedule.
    :param resolution:                  Timedelta used to resample the forecasts to the resolution of the schedule.
    :param soc_at_start:                State of charge at the start time.
    :param soc_targets:                 Exact targets for the state of charge at each time.
    :param soc_maxima:                  Maximum state of charge at each time.
    :param soc_minima:                  Minimum state of charge at each time.
    :param soc_max:                     Maximum state of charge at all times.
    :param soc_min:                     Minimum state of charge at all times.
    :returns:                           Constraints (StorageScheduler.COLUMNS) for a storage device, at each time step (index).
                                        See device_scheduler for possible column names.
    """

    # create empty storage device constraints dataframe
    storage_device_constraints = initialize_df(
        StorageScheduler.COLUMNS, start, end, resolution
    )

    if soc_targets is not None:
        # make an equality series with the SOC targets set in the flex model
        # storage_device_constraints refers to the flexible device we are scheduling
        storage_device_constraints["equals"] = build_device_soc_values(
            soc_targets, soc_at_start, start, end, resolution
        )

    soc_min_change = (soc_min - soc_at_start) * timedelta(hours=1) / resolution
    soc_max_change = (soc_max - soc_at_start) * timedelta(hours=1) / resolution

    if soc_minima is not None:
        storage_device_constraints["min"] = build_device_soc_values(
            soc_minima,
            soc_at_start,
            start,
            end,
            resolution,
        )

    storage_device_constraints["min"] = storage_device_constraints["min"].fillna(
        soc_min_change
    )

    if soc_maxima is not None:
        storage_device_constraints["max"] = build_device_soc_values(
            soc_maxima,
            soc_at_start,
            start,
            end,
            resolution,
        )

    storage_device_constraints["max"] = storage_device_constraints["max"].fillna(
        soc_max_change
    )

    # limiting max and min to be in the range [soc_min, soc_max]
    storage_device_constraints["min"] = storage_device_constraints["min"].clip(
        lower=soc_min_change, upper=soc_max_change
    )
    storage_device_constraints["max"] = storage_device_constraints["max"].clip(
        lower=soc_min_change, upper=soc_max_change
    )

    return storage_device_constraints


def validate_storage_constraints(
    constraints: pd.DataFrame,
    soc_at_start: float,
    min_soc: float,
    soc_max: float,
    resolution: timedelta,
) -> list[dict]:
    """Check that the storage constraints are fulfilled, e.g min <= equals <= max.

    A. Global validation
        A.1) min >= min_soc
        A.2) max <= soc_max
    B. Validation in the same time frame
        B.1) min <= max
        B.2) min <= equals
        B.3) equals <= max
    C. Validation in different time frames
        C.1) equals(t) - equals(t-1) <= `derivative max`(t)
        C.2) `derivative min`(t) <= equals(t) - equals(t-1)
        C.3) min(t) - max(t-1) <= `derivative max`(t)
        C.4) max(t) - min(t-1) >= `derivative min`(t)
        C.5) condition equals(t) - max(t-1) <= `derivative max`(t)
        C.6) `derivative min`(t) <= equals(t) - min(t-1)

    :param constraints:         dataframe containing the constraints of a storage device
    :param soc_at_start:        State of charge at the start time.
    :param min_soc:             Minimum state of charge at all times.
    :param soc_max:             Maximum state of charge at all times.
    :param resolution:          Constant duration between the start of each time step.
    :returns:                   List of constraint violations, specifying their time, constraint and violation.
    """

    constraint_violations = []

    ########################
    # A. Global validation #
    ########################

    # 1) min >= min_soc
    min_soc = (min_soc - soc_at_start) * timedelta(hours=1) / resolution
    constraint_violations += validate_constraint(
        constraints,
        "min",
        ">=",
        "min_soc",
        right_value=min_soc,
    )

    # 2) max <= soc_max
    soc_max = (soc_max - soc_at_start) * timedelta(hours=1) / resolution
    constraint_violations += validate_constraint(
        constraints,
        "max",
        "<=",
        "soc_max",
        right_value=soc_max,
    )

    ########################################
    # B. Validation in the same time frame #
    ########################################

    # 1) min <= max
    constraint_violations += validate_constraint(constraints, "min", "<=", "max")

    # 2) min <= equals
    constraint_violations += validate_constraint(constraints, "min", "<=", "equals")

    # 3) equals <= max
    constraint_violations += validate_constraint(constraints, "equals", "<=", "max")

    ##########################################
    # C. Validation in different time frames #
    ##########################################

    factor_w_wh = resolution / timedelta(hours=1)

    # compute diff_equals(t) =  equals(t) - equals(t-1)
    equals_extended = constraints["equals"].copy()
    # insert `soc_at_start` at time `constraints.index[0] - resolution` which creates a new entry at the end of the series
    equals_extended[constraints.index[0] - resolution] = soc_at_start
    # sort index to keep the time ordering
    equals_extended = equals_extended.sort_index()

    diff_equals = equals_extended.diff()[1:]

    # 1) equals(t) - equals(t-1) <= `derivative max`(t)

    mask = (
        ~(diff_equals <= constraints["derivative max"] * factor_w_wh)
        & ~diff_equals.isna()
    )
    time_condition_fails = constraints.index[mask]

    for dt in time_condition_fails:
        value_equals = constraints.loc[dt, "equals"]
        value_equals_previous = constraints.loc[dt - resolution, "equals"]
        value_derivative_max = constraints.loc[dt, "derivative max"]

        constraint_violations.append(
            dict(
                dt=dt.to_pydatetime(),
                condition="equals(t) - equals(t-1) <= `derivative max`(t)",
                violation=f"equals(t) [{value_equals}] - equals(t-1) [{value_equals_previous}] <= `derivative max`(t) [{value_derivative_max}]",
            )
        )

    # 2) `derivative min`(t) <= equals(t) - equals(t-1)

    mask = (
        ~((constraints["derivative min"] * factor_w_wh) <= diff_equals)
        & ~diff_equals.isna()
    )
    time_condition_fails = constraints.index[mask]

    for dt in time_condition_fails:
        value_equals = constraints.loc[dt, "equals"]
        value_equals_previous = constraints.loc[dt - resolution, "equals"]
        value_derivative_min = constraints.loc[dt, "derivative min"]

        constraint_violations.append(
            dict(
                dt=dt.to_pydatetime(),
                condition="`derivative min`(t) <= equals(t) - equals(t-1)",
                violation=f"`derivative min`(t) [{value_derivative_min}] <= equals(t) [{value_equals}] - equals(t-1) [{value_equals_previous}]",
            )
        )

    # extend max
    max_extended = constraints["max"].copy()
    # insert `soc_max` at time `constraints.index[0] - resolution` which creates a new entry at the end of the series
    max_extended[constraints.index[0] - resolution] = soc_max
    # sort index to keep the time ordering
    max_extended = max_extended.sort_index()

    # extend min
    min_extended = constraints["min"].copy()
    # insert `soc_max` at time `constraints.index[0] - resolution` which creates a new entry at the end of the series
    min_extended[constraints.index[0] - resolution] = min_soc
    # sort index to keep the time ordering
    min_extended = min_extended.sort_index()

    # 3) min(t) - max(t-1) <= `derivative max`(t)
    delta_min_max = min_extended - max_extended.shift(1)
    delta_min_max = delta_min_max[1:]

    condition3 = delta_min_max <= constraints["derivative max"] * factor_w_wh
    mask = ~condition3
    time_condition_fails = constraints.index[mask]

    for dt in time_condition_fails:
        value_min = constraints.loc[dt, "min"]
        value_max_previous = max_extended.loc[dt - resolution]
        value_derivative_max = constraints.loc[dt, "derivative max"]

        constraint_violations.append(
            dict(
                dt=dt.to_pydatetime(),
                condition="min(t) - max(t-1) <= `derivative max`(t)",
                violation=f"min(t) [{value_min}] - max(t-1) [{value_max_previous}] <= `derivative max`(t) [{value_derivative_max}]",
            )
        )

    # 4) max(t) - min(t-1) >= `derivative min`(t)
    delta_max_min = max_extended - min_extended.shift(1)
    delta_max_min = delta_max_min[1:]

    condition4 = delta_max_min >= constraints["derivative min"] * factor_w_wh
    mask = ~condition4
    time_condition_fails = constraints.index[mask]

    for dt in time_condition_fails:
        value_max = constraints.loc[dt, "max"]
        value_min_previous = min_extended.loc[dt - resolution]
        value_derivative_min = constraints.loc[dt, "derivative min"]

        constraint_violations.append(
            dict(
                dt=dt.to_pydatetime(),
                condition="max(t) - min(t-1) >= `derivative min`",
                violation=f"max(t) [{value_max}] - min(t-1) [{value_min_previous}] >= `derivative min`(t) [{value_derivative_min}]",
            )
        )

    # 5) equals(t) - max(t-1) <= `derivative max`(t)
    delta_equals_max = constraints["equals"] - max_extended.shift(1)
    delta_equals_max = delta_equals_max[1:]

    condition5 = delta_equals_max <= constraints["derivative max"] * factor_w_wh
    mask = ~condition5 & ~constraints["equals"].isna()
    time_condition_fails = constraints.index[mask]

    for dt in time_condition_fails:
        value_equals = constraints.loc[dt, "equals"]
        value_max_previous = max_extended.loc[dt - resolution]
        value_derivative_max = constraints.loc[dt, "derivative max"]

        constraint_violations.append(
            dict(
                dt=dt.to_pydatetime(),
                condition="equals(t) - max(t-1) <= `derivative max`(t)",
                violation=f"equals(t) [{value_equals}] - max(t-1) [{value_max_previous}] <= `derivative max`(t) [{value_derivative_max}]",
            )
        )

    # 6) `derivative min`(t) <= equals(t) - min(t-1)
    delta_equals_min = constraints["equals"] - min_extended.shift(1)
    delta_equals_min = delta_equals_min[1:]

    condition5 = delta_equals_min >= constraints["derivative min"] * factor_w_wh
    mask = ~condition5 & ~constraints["equals"].isna()
    time_condition_fails = constraints.index[mask]

    for dt in time_condition_fails:
        value_equals = constraints.loc[dt, "equals"]
        value_min_previous = min_extended.loc[dt - resolution]
        value_derivative_min = constraints.loc[dt, "derivative min"]

        constraint_violations.append(
            dict(
                dt=dt.to_pydatetime(),
                condition="`derivative min`(t) <= equals(t) - min(t-1)",
                violation=f"`derivative min`(t) [{value_derivative_min}] <= equals(t) [{value_equals}] - min(t-1) [{value_min_previous}]",
            )
        )

    return constraint_violations


def validate_constraint(
    constraints,
    left_constraint_name,
    inequality,
    right_constraint_name,
    left_value: float | None = None,
    right_value: float | None = None,
) -> list[dict]:
    """Validate the feasibility of a given set of constraints.

    :returns:                       List of constraint violations, specifying their time, constraint and violation.
    """
    mask = True
    if left_value is None:
        left_value = constraints[left_constraint_name]
        mask = mask & ~constraints[left_constraint_name].isna()
    if right_value is None:
        right_value = constraints[right_constraint_name]
        mask = mask & ~constraints[right_constraint_name].isna()
    if inequality == "<=":
        mask = mask & ~(left_value <= right_value)
    elif inequality == ">=":
        mask = mask & ~(left_value >= right_value)
    else:
        raise NotImplementedError(f"Inequality '{inequality}' not supported.")
    time_condition_fails = constraints.index[mask]
    constraint_violations = []
    for dt in time_condition_fails:
        lv = left_value[dt] if isinstance(left_value, pd.Series) else left_value
        rv = right_value[dt] if isinstance(right_value, pd.Series) else right_value
        constraint_violations.append(
            dict(
                dt=dt.to_pydatetime(),
                condition=f"{left_constraint_name} {inequality} {right_constraint_name}",
                violation=f"{left_constraint_name} [{lv}] {inequality} {right_constraint_name} [{rv}]",
            )
        )
    return constraint_violations


#####################
# TO BE DEPRECATED #
####################
@deprecated(build_device_soc_values, "0.14")
def build_device_soc_targets(
    targets: List[Dict[str, datetime | float]] | pd.Series,
    soc_at_start: float,
    start_of_schedule: datetime,
    end_of_schedule: datetime,
    resolution: timedelta,
) -> pd.Series:
    return build_device_soc_values(
        targets, soc_at_start, start_of_schedule, end_of_schedule, resolution
    )


StorageScheduler.compute_schedule = deprecated(StorageScheduler.compute, "0.14")(
    StorageScheduler.compute_schedule
)
