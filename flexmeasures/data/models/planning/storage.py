from __future__ import annotations

import re
import copy
from datetime import datetime, timedelta
from typing import Type

import pandas as pd
import numpy as np
from flask import current_app


from flexmeasures import Sensor
from flexmeasures.data.models.planning import Scheduler, SchedulerOutputType
from flexmeasures.data.models.planning.linear_optimization import device_scheduler
from flexmeasures.data.models.planning.utils import (
    get_prices,
    add_tiny_price_slope,
    initialize_series,
    initialize_df,
    get_power_values,
    fallback_charging_policy,
    get_continuous_series_sensor_or_quantity,
)
from flexmeasures.data.models.planning.exceptions import InfeasibleProblemException
from flexmeasures.data.schemas.scheduling.storage import StorageFlexModelSchema
from flexmeasures.data.schemas.scheduling import FlexContextSchema
from flexmeasures.utils.time_utils import get_max_planning_horizon
from flexmeasures.utils.coding_utils import deprecated
from flexmeasures.utils.unit_utils import ur, convert_units


class MetaStorageScheduler(Scheduler):
    """This class defines the constraints of a schedule for a storage device from the
    flex-model, flex-context, and sensor and asset attributes"""

    __version__ = None
    __author__ = "Seita"

    COLUMNS = [
        "equals",
        "max",
        "min",
        "efficiency",
        "derivative equals",
        "derivative max",
        "derivative min",
        "derivative down efficiency",
        "derivative up efficiency",
        "stock delta",
    ]

    def compute_schedule(self) -> pd.Series | None:
        """Schedule a battery or Charge Point based directly on the latest beliefs regarding market prices within the specified time window.
        For the resulting consumption schedule, consumption is defined as positive values.

        Deprecated method in v0.14. As an alternative, use MetaStorageScheduler.compute().
        """

        return self.compute()

    def _prepare(self, skip_validation: bool = False) -> tuple:  # noqa: C901
        """This function prepares the required data to compute the schedule:
            - price data
            - device constraint
            - ems constraints

        :param skip_validation: If True, skip validation of constraints specified in the data.
        :returns:               Input data for the scheduler
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
        storage_efficiency = self.flex_model.get("storage_efficiency")
        prefer_charging_sooner = self.flex_model.get("prefer_charging_sooner", True)

        consumption_price_sensor = (
            self.flex_context.get("consumption_price_sensor")
            or self.sensor.generic_asset.get_consumption_price_sensor()
        )
        production_price_sensor = (
            self.flex_context.get("production_price_sensor")
            or self.sensor.generic_asset.get_production_price_sensor()
        )
        consumption_price = self.flex_context.get("consumption_price")
        production_price = self.flex_context.get("production_price")
        inflexible_device_sensors = (
            self.flex_context.get("inflexible_device_sensors")
            or self.sensor.generic_asset.get_inflexible_device_sensors()
        )

        # Check for required Sensor attributes
        power_capacity_in_mw = self.flex_model.get(
            "power_capacity_in_mw",
            self.sensor.get_attribute("capacity_in_mw", None),
        )

        if power_capacity_in_mw is None:
            raise ValueError(
                "Power capacity is not defined in the sensor attributes or the flex-model."
            )

        if isinstance(power_capacity_in_mw, float) or isinstance(
            power_capacity_in_mw, int
        ):
            power_capacity_in_mw = ur.Quantity(f"{power_capacity_in_mw} MW")

        power_capacity_in_mw = get_continuous_series_sensor_or_quantity(
            variable_quantity=power_capacity_in_mw,
            actuator=sensor,
            unit="MW",
            query_window=(start, end),
            resolution=resolution,
            beliefs_before=belief_time,
        )

        # Check for known prices or price forecasts, trimming planning window accordingly
        if consumption_price is not None:
            up_deviation_prices = get_continuous_series_sensor_or_quantity(
                variable_quantity=consumption_price,
                actuator=sensor,
                unit=consumption_price.unit
                if isinstance(consumption_price, Sensor)
                else str(consumption_price.units),
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                fallback_attribute="market_id",
            ).to_frame()
        else:
            up_deviation_prices, (start, end) = get_prices(
                (start, end),
                resolution,
                beliefs_before=belief_time,
                price_sensor=consumption_price_sensor,
                sensor=sensor,
                allow_trimmed_query_window=False,
            )
        if production_price is not None:
            down_deviation_prices = get_continuous_series_sensor_or_quantity(
                variable_quantity=production_price,
                actuator=sensor,
                unit=production_price.unit
                if isinstance(production_price, Sensor)
                else str(production_price.units),
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                fallback_attribute="market_id",
            ).to_frame()
        else:
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

        # fetch SOC constraints from sensors
        if isinstance(soc_targets, Sensor):
            soc_targets = get_continuous_series_sensor_or_quantity(
                variable_quantity=soc_targets,
                actuator=sensor,
                unit="MWh",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                as_instantaneous_events=True,
                boundary_policy="first",
            )
        if isinstance(soc_minima, Sensor):
            soc_minima = get_continuous_series_sensor_or_quantity(
                variable_quantity=soc_minima,
                actuator=sensor,
                unit="MWh",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                as_instantaneous_events=True,
                boundary_policy="max",
            )
        if isinstance(soc_maxima, Sensor):
            soc_maxima = get_continuous_series_sensor_or_quantity(
                variable_quantity=soc_maxima,
                actuator=sensor,
                unit="MWh",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                as_instantaneous_events=True,
                boundary_policy="min",
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

        consumption_capacity = self.flex_model.get("consumption_capacity")
        production_capacity = self.flex_model.get("production_capacity")

        if sensor.get_attribute("is_strictly_non_positive"):
            device_constraints[0]["derivative min"] = 0
        else:
            device_constraints[0]["derivative min"] = (
                -1
            ) * get_continuous_series_sensor_or_quantity(
                variable_quantity=production_capacity,
                actuator=sensor,
                unit="MW",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                fallback_attribute="production_capacity",
                max_value=power_capacity_in_mw,
            )
        if sensor.get_attribute("is_strictly_non_negative"):
            device_constraints[0]["derivative max"] = 0
        else:
            device_constraints[0][
                "derivative max"
            ] = get_continuous_series_sensor_or_quantity(
                variable_quantity=consumption_capacity,
                actuator=sensor,
                unit="MW",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                fallback_attribute="consumption_capacity",
                max_value=power_capacity_in_mw,
            )

        soc_gain = self.flex_model.get("soc_gain", [])
        soc_usage = self.flex_model.get("soc_usage", [])

        all_stock_delta = []

        for is_usage, soc_delta in zip([False, True], [soc_gain, soc_usage]):
            for component in soc_delta:
                stock_delta_series = get_continuous_series_sensor_or_quantity(
                    variable_quantity=component,
                    actuator=sensor,
                    unit="MW",
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
                )

                # example: 4 MW sustained over 15 minutes gives 1 MWh
                stock_delta_series *= resolution / timedelta(
                    hours=1
                )  # MW -> MWh / resolution

                if is_usage:
                    stock_delta_series *= -1

                all_stock_delta.append(stock_delta_series)

        if len(all_stock_delta) > 0:
            all_stock_delta = pd.concat(all_stock_delta, axis=1)

            device_constraints[0]["stock delta"] = all_stock_delta.sum(1)
            device_constraints[0]["stock delta"] *= timedelta(hours=1) / resolution

        # Apply round-trip efficiency evenly to charging and discharging
        charging_efficiency = get_continuous_series_sensor_or_quantity(
            variable_quantity=self.flex_model.get("charging_efficiency"),
            actuator=sensor,
            unit="dimensionless",
            query_window=(start, end),
            resolution=resolution,
            beliefs_before=belief_time,
            fallback_attribute="charging-efficiency",
        ).fillna(1)
        discharging_efficiency = get_continuous_series_sensor_or_quantity(
            variable_quantity=self.flex_model.get("discharging_efficiency"),
            actuator=sensor,
            unit="dimensionless",
            query_window=(start, end),
            resolution=resolution,
            beliefs_before=belief_time,
            fallback_attribute="discharging-efficiency",
        ).fillna(1)

        roundtrip_efficiency = self.flex_model.get(
            "roundtrip_efficiency", self.sensor.get_attribute("roundtrip_efficiency", 1)
        )

        # if roundtrip efficiency is provided in the flex-model or defined as an asset attribute
        if "roundtrip_efficiency" in self.flex_model or self.sensor.has_attribute(
            "roundtrip-efficiency"
        ):
            charging_efficiency = roundtrip_efficiency**0.5
            discharging_efficiency = roundtrip_efficiency**0.5

        device_constraints[0]["derivative down efficiency"] = discharging_efficiency
        device_constraints[0]["derivative up efficiency"] = charging_efficiency

        # Apply storage efficiency (accounts for losses over time)
        if isinstance(storage_efficiency, ur.Quantity) or isinstance(
            storage_efficiency, Sensor
        ):
            device_constraints[0]["efficiency"] = (
                get_continuous_series_sensor_or_quantity(
                    variable_quantity=storage_efficiency,
                    actuator=sensor,
                    unit="dimensionless",
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fallback_attribute="storage_efficiency",  # this should become storage-efficiency
                    max_value=1,
                )
                .fillna(1.0)
                .clip(lower=0.0, upper=1.0)
            )
        elif storage_efficiency is not None:
            device_constraints[0]["efficiency"] = storage_efficiency

        # check that storage constraints are fulfilled
        if not skip_validation:
            constraint_violations = validate_storage_constraints(
                constraints=device_constraints[0],
                soc_at_start=soc_at_start,
                soc_min=soc_min,
                soc_max=soc_max,
                resolution=resolution,
            )

            if len(constraint_violations) > 0:
                # TODO: include hints from constraint_violations into the error message
                message = create_constraint_violations_message(constraint_violations)
                raise ValueError(
                    "The input data yields an infeasible problem. Constraint validation has found the following issues:\n"
                    + message
                )

        # Set up EMS constraints
        ems_constraints = initialize_df(
            StorageScheduler.COLUMNS, start, end, resolution
        )

        ems_power_capacity_in_mw = get_continuous_series_sensor_or_quantity(
            variable_quantity=self.flex_context.get("ems_power_capacity_in_mw"),
            actuator=sensor.generic_asset,
            unit="MW",
            query_window=(start, end),
            resolution=resolution,
            beliefs_before=belief_time,
            fallback_attribute="capacity_in_mw",
        )

        ems_constraints["derivative max"] = get_continuous_series_sensor_or_quantity(
            variable_quantity=self.flex_context.get("ems_consumption_capacity_in_mw"),
            actuator=sensor.generic_asset,
            unit="MW",
            query_window=(start, end),
            resolution=resolution,
            beliefs_before=belief_time,
            fallback_attribute="consumption_capacity_in_mw",
            max_value=ems_power_capacity_in_mw,
        )
        ems_constraints["derivative min"] = (
            -1
        ) * get_continuous_series_sensor_or_quantity(
            variable_quantity=self.flex_context.get("ems_production_capacity_in_mw"),
            actuator=sensor.generic_asset,
            unit="MW",
            query_window=(start, end),
            resolution=resolution,
            beliefs_before=belief_time,
            fallback_attribute="production_capacity_in_mw",
            max_value=ems_power_capacity_in_mw,
        )

        return (
            sensor,
            start,
            end,
            resolution,
            soc_at_start,
            device_constraints,
            ems_constraints,
            commitment_quantities,
            commitment_downwards_deviation_price,
            commitment_upwards_deviation_price,
        )

    def persist_flex_model(self):
        """Store new soc info as GenericAsset attributes"""
        self.sensor.generic_asset.set_attribute("soc_datetime", self.start.isoformat())
        self.sensor.generic_asset.set_attribute(
            "soc_in_mwh", self.flex_model["soc_at_start"]
        )

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

        self.ensure_soc_min_max()

        # Now it's time to check if our flex configuration holds up to schemas
        self.flex_model = StorageFlexModelSchema(
            start=self.start,
            sensor=self.sensor,
            default_soc_unit=self.flex_model.get("soc-unit"),
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

        if soc_targets and not isinstance(soc_targets, Sensor):
            max_target_datetime = max([soc_target["end"] for soc_target in soc_targets])
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

        # if the SOC targets are defined as a Sensor, we don't get min max values
        if isinstance(self.flex_model.get(soc_targets_label), dict):
            return None, None

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


class StorageFallbackScheduler(MetaStorageScheduler):
    __version__ = "1"
    __author__ = "Seita"

    def compute(self, skip_validation: bool = False) -> SchedulerOutputType:
        """Schedule a battery or Charge Point by just starting to charge, discharge, or do neither,
           depending on the first target state of charge and the capabilities of the Charge Point.
           For the resulting consumption schedule, consumption is defined as positive values.

           Note that this ignores any cause of the infeasibility.

        :param skip_validation: If True, skip validation of constraints specified in the data.
        :returns:               The computed schedule.
        """

        (
            sensor,
            start,
            end,
            resolution,
            soc_at_start,
            device_constraints,
            ems_constraints,
            commitment_quantities,
            commitment_downwards_deviation_price,
            commitment_upwards_deviation_price,
        ) = self._prepare(skip_validation=skip_validation)

        # Fallback policy if the problem was unsolvable
        storage_schedule = fallback_charging_policy(
            sensor, device_constraints[0], start, end, resolution
        )
        storage_schedule = convert_units(storage_schedule, "MW", sensor.unit)

        # Round schedule
        if self.round_to_decimals:
            storage_schedule = storage_schedule.round(self.round_to_decimals)

        if self.return_multiple:
            return [
                {
                    "name": "storage_schedule",
                    "sensor": sensor,
                    "data": storage_schedule,
                }
            ]
        else:
            return storage_schedule


class StorageScheduler(MetaStorageScheduler):
    __version__ = "3"
    __author__ = "Seita"

    fallback_scheduler_class: Type[Scheduler] = StorageFallbackScheduler

    def compute(self, skip_validation: bool = False) -> SchedulerOutputType:
        """Schedule a battery or Charge Point based directly on the latest beliefs regarding market prices within the specified time window.
        For the resulting consumption schedule, consumption is defined as positive values.

        :param skip_validation: If True, skip validation of constraints specified in the data.
        :returns:               The computed schedule.
        """

        (
            sensor,
            start,
            end,
            resolution,
            soc_at_start,
            device_constraints,
            ems_constraints,
            commitment_quantities,
            commitment_downwards_deviation_price,
            commitment_upwards_deviation_price,
        ) = self._prepare(skip_validation=skip_validation)

        ems_schedule, expected_costs, scheduler_results, _ = device_scheduler(
            device_constraints,
            ems_constraints,
            commitment_quantities,
            commitment_downwards_deviation_price,
            commitment_upwards_deviation_price,
            initial_stock=soc_at_start * (timedelta(hours=1) / resolution),
        )
        if scheduler_results.solver.termination_condition == "infeasible":
            raise InfeasibleProblemException()

        # Obtain the storage schedule from all device schedules within the EMS
        storage_schedule = ems_schedule[0]
        storage_schedule = convert_units(storage_schedule, "MW", sensor.unit)

        # Round schedule
        if self.round_to_decimals:
            storage_schedule = storage_schedule.round(self.round_to_decimals)

        if self.return_multiple:
            return [
                {
                    "name": "storage_schedule",
                    "sensor": sensor,
                    "data": storage_schedule,
                }
            ]
        else:
            return storage_schedule


def create_constraint_violations_message(constraint_violations: list) -> str:
    """Create a human-readable message with the constraint_violations.

    :param constraint_violations: list with the constraint violations
    :return: human-readable message
    """
    message = ""

    for c in constraint_violations:
        message += f"t={c['dt']} | {c['violation']}\n"

    if len(message) > 1:
        message = message[:-1]

    return message


def build_device_soc_values(
    soc_values: list[dict[str, datetime | float]] | pd.Series,
    soc_at_start: float,
    start_of_schedule: datetime,
    end_of_schedule: datetime,
    resolution: timedelta,
) -> pd.Series:
    """
    Utility function to create a Pandas series from SOC values we got from the flex-model.

    Should set NaN anywhere where there is no target.

    SOC values should be indexed by their due date. For example, for quarter-hourly targets from 5 to 6 AM:
    >>> df = pd.Series(data=[1, 1.5, 2, 2.5, 3], index=pd.date_range(pd.Timestamp("2010-01-01T05"), pd.Timestamp("2010-01-01T06"), freq=pd.Timedelta("PT15M"), inclusive="both"))
    >>> print(df)
    2010-01-01 05:00:00    1.0
    2010-01-01 05:15:00    1.5
    2010-01-01 05:30:00    2.0
    2010-01-01 05:45:00    2.5
    2010-01-01 06:00:00    3.0
    Freq: 15T, dtype: float64

    TODO: this function could become the deserialization method of a new TimedEventSchema (targets, plural), which wraps TimedEventSchema.

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

        max_server_horizon = get_max_planning_horizon(resolution)
        disregarded_periods: list[tuple[datetime, datetime]] = []
        for soc_value in soc_values:
            soc = soc_value["value"]
            # convert timezone, otherwise DST would be problematic
            soc_constraint_start = soc_value["start"].astimezone(
                device_values.index.tzinfo
            )
            soc_constraint_end = soc_value["end"].astimezone(device_values.index.tzinfo)
            if soc_constraint_end > end_of_schedule:
                # Skip too-far-into-the-future target
                disregarded_periods += [(soc_constraint_start, soc_constraint_end)]
                if soc_constraint_start <= end_of_schedule:
                    device_values.loc[soc_constraint_start:end_of_schedule] = soc
                continue

            device_values.loc[soc_constraint_start:soc_constraint_end] = soc

        if not disregarded_periods:
            pass
        elif len(disregarded_periods) == 1:
            soc_constraint_start, soc_constraint_end = disregarded_periods[0]
            if soc_constraint_start == soc_constraint_end:
                current_app.logger.warning(
                    f"Disregarding target datetime {soc_constraint_end}, because it exceeds {end_of_schedule}. Maximum scheduling horizon is {max_server_horizon}."
                )
            else:
                current_app.logger.warning(
                    f"Disregarding target datetimes that exceed {end_of_schedule} (within the window {soc_constraint_start} until {soc_constraint_end}). Maximum scheduling horizon is {max_server_horizon}."
                )
        else:
            soc_constraint_starts, soc_constraint_ends = zip(*disregarded_periods)
            current_app.logger.warning(
                f"Disregarding target datetimes that exceed {end_of_schedule} (within the window {min(soc_constraint_starts)} until {max(soc_constraint_ends)} spanning {len(disregarded_periods)} targets). Maximum scheduling horizon is {max_server_horizon}."
            )

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
    soc_targets: list[dict[str, datetime | float]] | pd.Series | None,
    soc_maxima: list[dict[str, datetime | float]] | pd.Series | None,
    soc_minima: list[dict[str, datetime | float]] | pd.Series | None,
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
    soc_min: float,
    soc_max: float,
    resolution: timedelta,
) -> list[dict]:
    """Check that the storage constraints are fulfilled, e.g min <= equals <= max.

    A. Global validation
        A.1) min >= soc_min
        A.2) max <= soc_max
    B. Validation in the same time frame
        B.1) min <= max
        B.2) min <= equals
        B.3) equals <= max
    C. Validation in different time frames
        C.1) equals(t) - equals(t-1) <= derivative_max(t)
        C.2) derivative_min(t) <= equals(t) - equals(t-1)
        C.3) min(t) - max(t-1) <= derivative_max(t)
        C.4) max(t) - min(t-1) >= derivative_min(t)
        C.5) equals(t) - max(t-1) <= derivative_max(t)
        C.6) derivative_min(t) <= equals(t) - min(t-1)

    :param constraints:         dataframe containing the constraints of a storage device
    :param soc_at_start:        State of charge at the start time.
    :param soc_min:             Minimum state of charge at all times.
    :param soc_max:             Maximum state of charge at all times.
    :param resolution:          Constant duration between the start of each time step.
    :returns:                   List of constraint violations, specifying their time, constraint and violation.
    """

    # get a copy of the constraints to make sure the dataframe doesn't get updated
    _constraints = constraints.copy()

    _constraints = _constraints.rename(
        columns={
            columns_name: columns_name.replace(" ", "_")
            + "(t)"  # replace spaces with underscore and add time index
            for columns_name in _constraints.columns
        }
    )

    constraint_violations = []

    ########################
    # A. Global validation #
    ########################

    # 1) min >= soc_min
    soc_min = (soc_min - soc_at_start) * timedelta(hours=1) / resolution
    _constraints["soc_min(t)"] = soc_min
    constraint_violations += validate_constraint(
        _constraints, "soc_min(t)", "<=", "min(t)"
    )

    # 2) max <= soc_max
    soc_max = (soc_max - soc_at_start) * timedelta(hours=1) / resolution
    _constraints["soc_max(t)"] = soc_max
    constraint_violations += validate_constraint(
        _constraints, "max(t)", "<=", "soc_max(t)"
    )

    ########################################
    # B. Validation in the same time frame #
    ########################################

    # 1) min <= max
    constraint_violations += validate_constraint(_constraints, "min(t)", "<=", "max(t)")

    # 2) min <= equals
    constraint_violations += validate_constraint(
        _constraints, "min(t)", "<=", "equals(t)"
    )

    # 3) equals <= max
    constraint_violations += validate_constraint(
        _constraints, "equals(t)", "<=", "max(t)"
    )

    ##########################################
    # C. Validation in different time frames #
    ##########################################

    _constraints["factor_w_wh(t)"] = resolution / timedelta(hours=1)
    _constraints["min(t-1)"] = prepend_serie(_constraints["min(t)"], soc_min)
    _constraints["equals(t-1)"] = prepend_serie(_constraints["equals(t)"], soc_at_start)
    _constraints["max(t-1)"] = prepend_serie(_constraints["max(t)"], soc_max)

    # 1) equals(t) - equals(t-1) <= derivative_max(t)
    constraint_violations += validate_constraint(
        _constraints,
        "equals(t) - equals(t-1)",
        "<=",
        "derivative_max(t) * factor_w_wh(t)",
    )

    # 2) derivative_min(t) <= equals(t) - equals(t-1)
    constraint_violations += validate_constraint(
        _constraints,
        "derivative_min(t) * factor_w_wh(t)",
        "<=",
        "equals(t) - equals(t-1)",
    )

    # 3) min(t) - max(t-1) <= derivative_max(t)
    constraint_violations += validate_constraint(
        _constraints, "min(t) - max(t-1)", "<=", "derivative_max(t) * factor_w_wh(t)"
    )

    # 4) max(t) - min(t-1) >= derivative_min(t)
    constraint_violations += validate_constraint(
        _constraints, "derivative_min(t) * factor_w_wh(t)", "<=", "max(t) - min(t-1)"
    )

    # 5) equals(t) - max(t-1) <= derivative_max(t)
    constraint_violations += validate_constraint(
        _constraints, "equals(t) - max(t-1)", "<=", "derivative_max(t) * factor_w_wh(t)"
    )

    # 6) derivative_min(t) <= equals(t) - min(t-1)
    constraint_violations += validate_constraint(
        _constraints, "derivative_min(t) * factor_w_wh(t)", "<=", "equals(t) - min(t-1)"
    )

    return constraint_violations


def get_pattern_match_word(word: str) -> str:
    """Get a regex pattern to match a word

    The conditions to delimit a word are:
      - start of line
      - whitespace
      - end of line
      - word boundary
      - arithmetic operations

    :return: regex expression
    """

    regex = r"(^|\s|$|\b|\+|\-|\*|\/\|\\)"

    return regex + re.escape(word) + regex


def sanitize_expression(expression: str, columns: list) -> tuple[str, list]:
    """Wrap column in commas to accept arbitrary column names (e.g. with spaces).

    :param expression: expression to sanitize
    :param columns: list with the name of the columns of the input data for the expression.
    :return: sanitized expression and columns (variables) used in the expression
    """

    _expression = copy.copy(expression)
    columns_involved = []

    for column in columns:
        if re.search(get_pattern_match_word(column), _expression):
            columns_involved.append(column)

        _expression = re.sub(get_pattern_match_word(column), f"`{column}`", _expression)

    return _expression, columns_involved


def validate_constraint(
    constraints_df: pd.DataFrame,
    lhs_expression: str,
    inequality: str,
    rhs_expression: str,
    round_to_decimals: int | None = 6,
) -> list[dict]:
    """Validate the feasibility of a given set of constraints.

    :param constraints_df:      DataFrame with the constraints
    :param lhs_expression:      left-hand side of the inequality expression following pd.eval format.
                                No need to use the syntax `column` to reference
                                column, just use the column name.
    :param inequality:          inequality operator, one of ('<=', '<', '>=', '>', '==', '!=').
    :param rhs_expression:      right-hand side of the inequality expression following pd.eval format.
                                No need to use the syntax `column` to reference
                                column, just use the column name.
    :param round_to_decimals:   Number of decimals to round off to before validating constraints.
    :return:                    List of constraint violations, specifying their time, constraint and violation.
    """

    constraint_expression = f"{lhs_expression} {inequality} {rhs_expression}"

    constraints_df_columns = list(constraints_df.columns)

    lhs_expression, columns_lhs = sanitize_expression(
        lhs_expression, constraints_df_columns
    )
    rhs_expression, columns_rhs = sanitize_expression(
        rhs_expression, constraints_df_columns
    )

    columns_involved = columns_lhs + columns_rhs

    lhs = constraints_df.fillna(0).eval(lhs_expression).round(round_to_decimals)
    rhs = constraints_df.fillna(0).eval(rhs_expression).round(round_to_decimals)

    condition = None

    inequality = inequality.strip()

    if inequality == "<=":
        condition = lhs <= rhs
    elif inequality == "<":
        condition = lhs < rhs
    elif inequality == ">=":
        condition = lhs >= rhs
    elif inequality == ">":
        condition = lhs > rhs
    elif inequality == "==":
        condition = lhs == rhs
    elif inequality == "!=":
        condition = lhs != rhs
    else:
        raise ValueError(f"Inequality `{inequality} not supported.")

    time_condition_fails = constraints_df.index[
        ~condition & ~constraints_df[columns_involved].isna().any(axis=1)
    ]

    constraint_violations = []

    for dt in time_condition_fails:
        value_replaced = copy.copy(constraint_expression)

        for column in constraints_df.columns:
            value_replaced = re.sub(
                get_pattern_match_word(column),
                f"{column} [{constraints_df.loc[dt, column]}] ",
                value_replaced,
            )

        constraint_violations.append(
            dict(
                dt=dt.to_pydatetime(),
                condition=constraint_expression,
                violation=value_replaced,
            )
        )

    return constraint_violations


def prepend_serie(serie: pd.Series, value) -> pd.Series:
    """Prepend a value to a time series series

    :param serie: serie containing the timed values
    :param value: value to place in the first position
    """
    # extend max
    serie = serie.copy()
    # insert `value` at time `serie.index[0] - resolution` which creates a new entry at the end of the series
    serie[serie.index[0] - serie.index.freq] = value
    # sort index to keep the time ordering
    serie = serie.sort_index()
    return serie.shift(1)


#####################
# TO BE DEPRECATED #
####################
@deprecated(build_device_soc_values, "0.14")
def build_device_soc_targets(
    targets: list[dict[str, datetime | float]] | pd.Series,
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
