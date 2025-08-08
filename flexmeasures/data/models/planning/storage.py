from __future__ import annotations

import re
import copy
from datetime import datetime, timedelta
from typing import Type

import pandas as pd
import numpy as np
from flask import current_app


from flexmeasures import Sensor
from flexmeasures.data.models.planning import (
    FlowCommitment,
    Scheduler,
    SchedulerOutputType,
    StockCommitment,
)
from flexmeasures.data.models.planning.linear_optimization import device_scheduler
from flexmeasures.data.models.planning.utils import (
    add_tiny_price_slope,
    ensure_prices_are_not_empty,
    initialize_index,
    initialize_series,
    initialize_df,
    get_power_values,
    fallback_charging_policy,
    get_continuous_series_sensor_or_quantity,
)
from flexmeasures.data.models.planning.exceptions import InfeasibleProblemException
from flexmeasures.data.schemas.scheduling.storage import StorageFlexModelSchema
from flexmeasures.data.schemas.scheduling import (
    FlexContextSchema,
    MultiSensorFlexModelSchema,
)
from flexmeasures.utils.calculations import (
    integrate_time_series,
)
from flexmeasures.utils.time_utils import get_max_planning_horizon
from flexmeasures.utils.coding_utils import deprecated
from flexmeasures.utils.time_utils import determine_minimum_resampling_resolution
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

        # List the asset and sensor(s) being scheduled
        if self.asset is not None:
            sensors = [flex_model_d["sensor"] for flex_model_d in self.flex_model]
            resolution = determine_minimum_resampling_resolution(
                [s.event_resolution for s in sensors]
            )
            asset = self.asset
        else:
            # For backwards compatibility with the single asset scheduler
            sensors = [self.sensor]
            asset = self.sensor.generic_asset

        # For backwards compatibility with the single asset scheduler
        flex_model = self.flex_model
        if not isinstance(flex_model, list):
            flex_model = [flex_model]

        # total number of flexible devices D described in the flex-model
        num_flexible_devices = len(flex_model)

        soc_at_start = [flex_model_d.get("soc_at_start") for flex_model_d in flex_model]
        soc_targets = [flex_model_d.get("soc_targets") for flex_model_d in flex_model]
        soc_min = [flex_model_d.get("soc_min") for flex_model_d in flex_model]
        soc_max = [flex_model_d.get("soc_max") for flex_model_d in flex_model]
        soc_minima = [flex_model_d.get("soc_minima") for flex_model_d in flex_model]
        soc_maxima = [flex_model_d.get("soc_maxima") for flex_model_d in flex_model]
        storage_efficiency = [
            flex_model_d.get("storage_efficiency") for flex_model_d in flex_model
        ]
        prefer_charging_sooner = [
            flex_model_d.get("prefer_charging_sooner") for flex_model_d in flex_model
        ]
        prefer_curtailing_later = [
            flex_model_d.get("prefer_curtailing_later") for flex_model_d in flex_model
        ]
        soc_gain = [flex_model_d.get("soc_gain") for flex_model_d in flex_model]
        soc_usage = [flex_model_d.get("soc_usage") for flex_model_d in flex_model]
        consumption_capacity = [
            flex_model_d.get("consumption_capacity") for flex_model_d in flex_model
        ]
        production_capacity = [
            flex_model_d.get("production_capacity") for flex_model_d in flex_model
        ]
        charging_efficiency = [
            flex_model_d.get("charging_efficiency") for flex_model_d in flex_model
        ]
        discharging_efficiency = [
            flex_model_d.get("discharging_efficiency") for flex_model_d in flex_model
        ]

        # Get info from flex-context
        consumption_price_sensor = self.flex_context.get("consumption_price_sensor")
        production_price_sensor = self.flex_context.get("production_price_sensor")
        consumption_price = self.flex_context.get(
            "consumption_price", consumption_price_sensor
        )
        production_price = self.flex_context.get(
            "production_price", production_price_sensor
        )
        # fallback to using the consumption price, for backwards compatibility
        if production_price is None:
            production_price = consumption_price
        inflexible_device_sensors = self.flex_context.get(
            "inflexible_device_sensors", []
        )

        # Fetch the device's power capacity (required Sensor attribute)
        power_capacity_in_mw = self._get_device_power_capacity(flex_model, sensors)

        # Check for known prices or price forecasts
        up_deviation_prices = get_continuous_series_sensor_or_quantity(
            variable_quantity=consumption_price,
            actuator=asset,
            unit=self.flex_context["shared_currency_unit"] + "/MWh",
            query_window=(start, end),
            resolution=resolution,
            beliefs_before=belief_time,
            fill_sides=True,
        ).to_frame(name="event_value")
        ensure_prices_are_not_empty(up_deviation_prices, consumption_price)
        down_deviation_prices = get_continuous_series_sensor_or_quantity(
            variable_quantity=production_price,
            actuator=asset,
            unit=self.flex_context["shared_currency_unit"] + "/MWh",
            query_window=(start, end),
            resolution=resolution,
            beliefs_before=belief_time,
            fill_sides=True,
        ).to_frame(name="event_value")
        ensure_prices_are_not_empty(down_deviation_prices, production_price)

        start = pd.Timestamp(start).tz_convert("UTC")
        end = pd.Timestamp(end).tz_convert("UTC")

        # Add tiny price slope to prefer charging now rather than later, and discharging later rather than now.
        # We penalise future consumption and reward future production with at most 1 per thousand times the energy price spread.
        # todo: move to flow or stock commitment per device
        if any(prefer_charging_sooner):
            up_deviation_prices = add_tiny_price_slope(
                up_deviation_prices, "event_value"
            )
            down_deviation_prices = add_tiny_price_slope(
                down_deviation_prices, "event_value"
            )

        # Create Series with EMS capacities
        ems_power_capacity_in_mw = get_continuous_series_sensor_or_quantity(
            variable_quantity=self.flex_context.get("ems_power_capacity_in_mw"),
            actuator=asset,
            unit="MW",
            query_window=(start, end),
            resolution=resolution,
            beliefs_before=belief_time,
            resolve_overlaps="min",
        )
        ems_consumption_capacity = get_continuous_series_sensor_or_quantity(
            variable_quantity=self.flex_context.get("ems_consumption_capacity_in_mw"),
            actuator=asset,
            unit="MW",
            query_window=(start, end),
            resolution=resolution,
            beliefs_before=belief_time,
            max_value=ems_power_capacity_in_mw,
            resolve_overlaps="min",
        )
        ems_production_capacity = -1 * get_continuous_series_sensor_or_quantity(
            variable_quantity=self.flex_context.get("ems_production_capacity_in_mw"),
            actuator=asset,
            unit="MW",
            query_window=(start, end),
            resolution=resolution,
            beliefs_before=belief_time,
            max_value=ems_power_capacity_in_mw,
            resolve_overlaps="min",
        )

        # Set up commitments to optimise for
        commitments = []

        index = initialize_index(start, end, resolution)
        commitment_quantities = initialize_series(0, start, end, resolution)

        # Convert energy prices to EUR/(deviation of commitment, which is in MW)
        commitment_upwards_deviation_price = (
            up_deviation_prices.loc[start : end - resolution]["event_value"]
            * resolution
            / pd.Timedelta("1h")
        )
        commitment_downwards_deviation_price = (
            down_deviation_prices.loc[start : end - resolution]["event_value"]
            * resolution
            / pd.Timedelta("1h")
        )

        # Set up commitments DataFrame
        commitment = FlowCommitment(
            name="energy",
            quantity=commitment_quantities,
            upwards_deviation_price=commitment_upwards_deviation_price,
            downwards_deviation_price=commitment_downwards_deviation_price,
            index=index,
        )
        commitments.append(commitment)

        # Set up peak commitments
        if self.flex_context.get("ems_peak_consumption_price") is not None:
            ems_peak_consumption = get_continuous_series_sensor_or_quantity(
                variable_quantity=self.flex_context.get("ems_peak_consumption_in_mw"),
                actuator=asset,
                unit="MW",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                max_value=np.inf,  # np.nan -> np.inf to ignore commitment if no quantity is given
                fill_sides=True,
            )
            ems_peak_consumption_price = self.flex_context.get(
                "ems_peak_consumption_price"
            )
            ems_peak_consumption_price = get_continuous_series_sensor_or_quantity(
                variable_quantity=ems_peak_consumption_price,
                actuator=asset,
                unit=self.flex_context["shared_currency_unit"] + "/MW",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                fill_sides=True,
            )

            # Set up commitments DataFrame
            commitment = FlowCommitment(
                name="consumption peak",
                quantity=ems_peak_consumption,
                # positive price because breaching in the upwards (consumption) direction is penalized
                upwards_deviation_price=ems_peak_consumption_price,
                _type="any",
                index=index,
            )
            commitments.append(commitment)
        if self.flex_context.get("ems_peak_production_price") is not None:
            ems_peak_production = get_continuous_series_sensor_or_quantity(
                variable_quantity=self.flex_context.get("ems_peak_production_in_mw"),
                actuator=asset,
                unit="MW",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                max_value=np.inf,  # np.nan -> np.inf to ignore commitment if no quantity is given
                fill_sides=True,
            )
            ems_peak_production_price = self.flex_context.get(
                "ems_peak_production_price"
            )
            ems_peak_production_price = get_continuous_series_sensor_or_quantity(
                variable_quantity=ems_peak_production_price,
                actuator=asset,
                unit=self.flex_context["shared_currency_unit"] + "/MW",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                fill_sides=True,
            )

            # Set up commitments DataFrame
            commitment = FlowCommitment(
                name="production peak",
                quantity=-ems_peak_production,  # production is negative quantity
                # negative price because peaking in the downwards (production) direction is penalized
                downwards_deviation_price=-ems_peak_production_price,
                _type="any",
                index=index,
            )
            commitments.append(commitment)

        # Set up capacity breach commitments and EMS capacity constraints
        ems_consumption_breach_price = self.flex_context.get(
            "ems_consumption_breach_price"
        )

        ems_production_breach_price = self.flex_context.get(
            "ems_production_breach_price"
        )

        ems_constraints = initialize_df(
            StorageScheduler.COLUMNS, start, end, resolution
        )
        if ems_consumption_breach_price is not None:

            # Convert to Series
            any_ems_consumption_breach_price = get_continuous_series_sensor_or_quantity(
                variable_quantity=ems_consumption_breach_price,
                actuator=asset,
                unit=self.flex_context["shared_currency_unit"] + "/MW",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                fill_sides=True,
            )
            all_ems_consumption_breach_price = get_continuous_series_sensor_or_quantity(
                variable_quantity=ems_consumption_breach_price,
                actuator=asset,
                unit=self.flex_context["shared_currency_unit"]
                + "/MW*h",  # from EUR/MWh to EUR/MW/resolution
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                fill_sides=True,
            )

            # Set up commitments DataFrame to penalize any breach
            commitment = FlowCommitment(
                name="any consumption breach",
                quantity=ems_consumption_capacity,
                # positive price because breaching in the upwards (consumption) direction is penalized
                upwards_deviation_price=any_ems_consumption_breach_price,
                _type="any",
                index=index,
            )
            commitments.append(commitment)

            # Set up commitments DataFrame to penalize each breach
            commitment = FlowCommitment(
                name="all consumption breaches",
                quantity=ems_consumption_capacity,
                # positive price because breaching in the upwards (consumption) direction is penalized
                upwards_deviation_price=all_ems_consumption_breach_price,
                index=index,
            )
            commitments.append(commitment)

            # Take the physical capacity as a hard constraint
            ems_constraints["derivative max"] = ems_power_capacity_in_mw
        else:
            # Take the contracted capacity as a hard constraint
            ems_constraints["derivative max"] = ems_consumption_capacity

        if ems_production_breach_price is not None:

            # Convert to Series
            any_ems_production_breach_price = get_continuous_series_sensor_or_quantity(
                variable_quantity=ems_production_breach_price,
                actuator=asset,
                unit=self.flex_context["shared_currency_unit"] + "/MW",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                fill_sides=True,
            )
            all_ems_production_breach_price = get_continuous_series_sensor_or_quantity(
                variable_quantity=ems_production_breach_price,
                actuator=asset,
                unit=self.flex_context["shared_currency_unit"]
                + "/MW*h",  # from EUR/MWh to EUR/MW/resolution
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                fill_sides=True,
            )

            # Set up commitments DataFrame to penalize any breach
            commitment = FlowCommitment(
                name="any production breach",
                quantity=ems_production_capacity,
                # negative price because breaching in the downwards (production) direction is penalized
                downwards_deviation_price=-any_ems_production_breach_price,
                _type="any",
                index=index,
            )
            commitments.append(commitment)

            # Set up commitments DataFrame to penalize each breach
            commitment = FlowCommitment(
                name="all production breaches",
                quantity=ems_production_capacity,
                # negative price because breaching in the downwards (production) direction is penalized
                downwards_deviation_price=-all_ems_production_breach_price,
                index=index,
            )
            commitments.append(commitment)

            # Take the physical capacity as a hard constraint
            ems_constraints["derivative min"] = -ems_power_capacity_in_mw
        else:
            # Take the contracted capacity as a hard constraint
            ems_constraints["derivative min"] = ems_production_capacity

        # Flow commitments per device

        # Add tiny price slope to prefer curtailing later rather than now.
        # The price slope is half of the slope to prefer charging sooner
        for d, prefer_curtailing_later_d in enumerate(prefer_curtailing_later):
            if prefer_curtailing_later_d:
                tiny_price_slope = (
                    add_tiny_price_slope(up_deviation_prices, "event_value")
                    - up_deviation_prices
                )
                tiny_price_slope *= 0.5
                commitment = FlowCommitment(
                    name=f"prefer curtailing device {d} later",
                    # Prefer curtailing consumption later by penalizing later consumption
                    upwards_deviation_price=tiny_price_slope,
                    # Prefer curtailing production later by penalizing later production
                    downwards_deviation_price=-tiny_price_slope,
                    index=index,
                    device=d,
                )
                commitments.append(commitment)

        # Set up device constraints: scheduled flexible devices for this EMS (from index 0 to D-1), plus the forecasted inflexible devices (at indices D to n).
        device_constraints = [
            initialize_df(StorageScheduler.COLUMNS, start, end, resolution)
            for i in range(num_flexible_devices + len(inflexible_device_sensors))
        ]
        for i, inflexible_sensor in enumerate(inflexible_device_sensors):
            device_constraints[i + num_flexible_devices]["derivative equals"] = (
                get_power_values(
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    sensor=inflexible_sensor,
                )
            )

        # Create the device constraints for all the flexible devices
        for d in range(num_flexible_devices):
            sensor_d = sensors[d]

            # fetch SOC constraints from sensors
            if isinstance(soc_targets[d], Sensor):
                soc_targets[d] = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_targets[d],
                    actuator=sensor_d,
                    unit="MWh",
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    as_instantaneous_events=True,
                    resolve_overlaps="first",
                )
                # todo: check flex-model for soc_minima_breach_price and soc_maxima_breach_price fields; if these are defined, create a StockCommitment using both prices (if only 1 price is given, still create the commitment, but only penalize one direction)
            if isinstance(soc_minima[d], Sensor):
                soc_minima[d] = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_minima[d],
                    actuator=sensor_d,
                    unit="MWh",
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    as_instantaneous_events=True,
                    resolve_overlaps="max",
                )
            if (
                self.flex_context.get("soc_minima_breach_price") is not None
                and soc_minima[d] is not None
            ):
                soc_minima_breach_price = self.flex_context["soc_minima_breach_price"]
                any_soc_minima_breach_price = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_minima_breach_price,
                    actuator=asset,
                    unit=self.flex_context["shared_currency_unit"] + "/MWh",
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fallback_attribute="soc-minima-breach-price",
                    fill_sides=True,
                ).shift(-1, freq=resolution)
                all_soc_minima_breach_price = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_minima_breach_price,
                    actuator=asset,
                    unit=self.flex_context["shared_currency_unit"]
                    + "/MWh*h",  # from EUR/MWh² to EUR/MWh/resolution
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fallback_attribute="soc-minima-breach-price",
                    fill_sides=True,
                ).shift(-1, freq=resolution)
                # Set up commitments DataFrame
                # soc_minima_d is a temp variable because add_storage_constraints can't deal with Series yet
                soc_minima_d = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_minima[d],
                    actuator=sensor_d,
                    unit="MWh",
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    as_instantaneous_events=True,
                    resolve_overlaps="max",
                )
                # shift soc minima by one resolution (they define a state at a certain time,
                # while the commitment defines what the total stock should be at the end of a time slot,
                # where the time slot is indexed by its starting time)
                soc_minima_d = soc_minima_d.shift(-1, freq=resolution) * (
                    timedelta(hours=1) / resolution
                ) - soc_at_start[d] * (timedelta(hours=1) / resolution)

                commitment = StockCommitment(
                    name="any soc minima",
                    quantity=soc_minima_d,
                    # negative price because breaching in the downwards (shortage) direction is penalized
                    downwards_deviation_price=-any_soc_minima_breach_price,
                    index=index,
                    _type="any",
                    device=d,
                )
                commitments.append(commitment)

                commitment = StockCommitment(
                    name="all soc minima",
                    quantity=soc_minima_d,
                    # negative price because breaching in the downwards (shortage) direction is penalized
                    downwards_deviation_price=-all_soc_minima_breach_price,
                    index=index,
                    device=d,
                )
                commitments.append(commitment)

                # soc-minima will become a soft constraint (modelled as stock commitments), so remove hard constraint
                soc_minima[d] = None

            if isinstance(soc_maxima[d], Sensor):
                soc_maxima[d] = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_maxima[d],
                    actuator=sensor_d,
                    unit="MWh",
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    as_instantaneous_events=True,
                    resolve_overlaps="min",
                )
            if (
                self.flex_context.get("soc_maxima_breach_price") is not None
                and soc_maxima[d] is not None
            ):
                soc_maxima_breach_price = self.flex_context["soc_maxima_breach_price"]
                any_soc_maxima_breach_price = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_maxima_breach_price,
                    actuator=asset,
                    unit=self.flex_context["shared_currency_unit"] + "/MWh",
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fallback_attribute="soc-maxima-breach-price",
                    fill_sides=True,
                ).shift(-1, freq=resolution)
                all_soc_maxima_breach_price = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_maxima_breach_price,
                    actuator=asset,
                    unit=self.flex_context["shared_currency_unit"]
                    + "/MWh*h",  # from EUR/MWh² to EUR/MWh/resolution
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fallback_attribute="soc-maxima-breach-price",
                    fill_sides=True,
                ).shift(-1, freq=resolution)
                # Set up commitments DataFrame
                # soc_maxima_d is a temp variable because add_storage_constraints can't deal with Series yet
                soc_maxima_d = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_maxima[d],
                    actuator=sensor_d,
                    unit="MWh",
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    as_instantaneous_events=True,
                    resolve_overlaps="min",
                )
                # shift soc maxima by one resolution (they define a state at a certain time,
                # while the commitment defines what the total stock should be at the end of a time slot,
                # where the time slot is indexed by its starting time)
                soc_maxima_d = soc_maxima_d.shift(-1, freq=resolution) * (
                    timedelta(hours=1) / resolution
                ) - soc_at_start[d] * (timedelta(hours=1) / resolution)

                commitment = StockCommitment(
                    name="any soc maxima",
                    quantity=soc_maxima_d,
                    # positive price because breaching in the upwards (surplus) direction is penalized
                    upwards_deviation_price=any_soc_maxima_breach_price,
                    index=index,
                    _type="any",
                    device=d,
                )
                commitments.append(commitment)

                commitment = StockCommitment(
                    name="all soc maxima",
                    quantity=soc_maxima_d,
                    # positive price because breaching in the upwards (surplus) direction is penalized
                    upwards_deviation_price=all_soc_maxima_breach_price,
                    index=index,
                    device=d,
                )
                commitments.append(commitment)

                # soc-maxima will become a soft constraint (modelled as stock commitments), so remove hard constraint
                soc_maxima[d] = None

            if soc_at_start[d] is not None:
                device_constraints[d] = add_storage_constraints(
                    start,
                    end,
                    resolution,
                    soc_at_start[d],
                    soc_targets[d],
                    soc_maxima[d],
                    soc_minima[d],
                    soc_max[d],
                    soc_min[d],
                )
            else:
                # No need to validate non-existing storage constraints
                skip_validation = True

            power_capacity_in_mw[d] = get_continuous_series_sensor_or_quantity(
                variable_quantity=power_capacity_in_mw[d],
                actuator=sensor_d,
                unit="MW",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                min_value=0,  # capacities are positive by definition
                resolve_overlaps="min",
            )
            device_constraints[d]["derivative max"] = power_capacity_in_mw[d]
            device_constraints[d]["derivative min"] = -power_capacity_in_mw[d]

            if sensor_d.get_attribute("is_strictly_non_positive"):
                device_constraints[d]["derivative min"] = 0
            else:
                production_capacity_d = get_continuous_series_sensor_or_quantity(
                    variable_quantity=production_capacity[d],
                    actuator=sensor_d,
                    unit="MW",
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fallback_attribute="production_capacity",
                    max_value=power_capacity_in_mw[d],
                    min_value=0,  # capacities are positive by definition
                    resolve_overlaps="min",
                )
                if (
                    self.flex_context.get("production_breach_price") is not None
                    and production_capacity[d] is not None
                ):
                    # consumption-capacity will become a soft constraint
                    production_breach_price = self.flex_context[
                        "production_breach_price"
                    ]
                    any_production_breach_price = (
                        get_continuous_series_sensor_or_quantity(
                            variable_quantity=production_breach_price,
                            actuator=asset,
                            unit=self.flex_context["shared_currency_unit"] + "/MW",
                            query_window=(start, end),
                            resolution=resolution,
                            beliefs_before=belief_time,
                            fallback_attribute="production-breach-price",
                            fill_sides=True,
                        )
                    )
                    all_production_breach_price = (
                        get_continuous_series_sensor_or_quantity(
                            variable_quantity=production_breach_price,
                            actuator=asset,
                            unit=self.flex_context["shared_currency_unit"]
                            + "/MW*h",  # from EUR/MWh to EUR/MW/resolution
                            query_window=(start, end),
                            resolution=resolution,
                            beliefs_before=belief_time,
                            fallback_attribute="production-breach-price",
                            fill_sides=True,
                        )
                    )
                    # Set up commitments DataFrame
                    commitment = FlowCommitment(
                        name=f"any production breach device {d}",
                        quantity=-production_capacity_d,
                        # negative price because breaching in the downwards (production) direction is penalized
                        downwards_deviation_price=-any_production_breach_price,
                        index=index,
                        _type="any",
                        device=d,
                    )
                    commitments.append(commitment)

                    commitment = FlowCommitment(
                        name=f"all production breaches device {d}",
                        quantity=-production_capacity_d,
                        # negative price because breaching in the downwards (production) direction is penalized
                        downwards_deviation_price=-all_production_breach_price,
                        index=index,
                        device=d,
                    )
                    commitments.append(commitment)
                else:
                    # consumption-capacity will become a hard constraint
                    device_constraints[d]["derivative min"] = -production_capacity_d
            if sensor_d.get_attribute("is_strictly_non_negative"):
                device_constraints[d]["derivative max"] = 0
            else:
                consumption_capacity_d = get_continuous_series_sensor_or_quantity(
                    variable_quantity=consumption_capacity[d],
                    actuator=sensor_d,
                    unit="MW",
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fallback_attribute="consumption_capacity",
                    min_value=0,  # capacities are positive by definition
                    max_value=power_capacity_in_mw[d],
                    resolve_overlaps="min",
                )
                if (
                    self.flex_context.get("consumption_breach_price") is not None
                    and consumption_capacity[d] is not None
                ):
                    # consumption-capacity will become a soft constraint
                    consumption_breach_price = self.flex_context[
                        "consumption_breach_price"
                    ]
                    any_consumption_breach_price = (
                        get_continuous_series_sensor_or_quantity(
                            variable_quantity=consumption_breach_price,
                            actuator=asset,
                            unit=self.flex_context["shared_currency_unit"] + "/MW",
                            query_window=(start, end),
                            resolution=resolution,
                            beliefs_before=belief_time,
                            fallback_attribute="consumption-breach-price",
                            fill_sides=True,
                        )
                    )
                    all_consumption_breach_price = (
                        get_continuous_series_sensor_or_quantity(
                            variable_quantity=consumption_breach_price,
                            actuator=asset,
                            unit=self.flex_context["shared_currency_unit"]
                            + "/MW*h",  # from EUR/MWh to EUR/MW/resolution
                            query_window=(start, end),
                            resolution=resolution,
                            beliefs_before=belief_time,
                            fallback_attribute="consumption-breach-price",
                            fill_sides=True,
                        )
                    )
                    # Set up commitments DataFrame
                    commitment = FlowCommitment(
                        name=f"any consumption breach device {d}",
                        quantity=consumption_capacity_d,
                        upwards_deviation_price=any_consumption_breach_price,
                        index=index,
                        _type="any",
                        device=d,
                    )
                    commitments.append(commitment)

                    commitment = FlowCommitment(
                        name=f"all consumption breaches device {d}",
                        quantity=consumption_capacity_d,
                        upwards_deviation_price=all_consumption_breach_price,
                        index=index,
                        device=d,
                    )
                    commitments.append(commitment)
                else:
                    # consumption-capacity will become a hard constraint
                    device_constraints[d]["derivative max"] = consumption_capacity_d

            all_stock_delta = []

            for is_usage, soc_delta in zip([False, True], [soc_gain[d], soc_usage[d]]):
                if soc_delta is None:
                    # Try to get fallback
                    soc_delta = [None]

                for component in soc_delta:
                    stock_delta_series = get_continuous_series_sensor_or_quantity(
                        variable_quantity=component,
                        actuator=sensor_d,
                        unit="MW",
                        query_window=(start, end),
                        resolution=resolution,
                        beliefs_before=belief_time,
                        fallback_attribute="soc-usage" if is_usage else "soc-gain",
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

                device_constraints[d]["stock delta"] = all_stock_delta.sum(1)
                device_constraints[d]["stock delta"] *= timedelta(hours=1) / resolution

            # Apply round-trip efficiency evenly to charging and discharging
            charging_efficiency[d] = (
                get_continuous_series_sensor_or_quantity(
                    variable_quantity=charging_efficiency[d],
                    actuator=sensor_d,
                    unit="dimensionless",
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fallback_attribute="charging-efficiency",
                )
                .astype(float)
                .fillna(1)
            )
            discharging_efficiency[d] = (
                get_continuous_series_sensor_or_quantity(
                    variable_quantity=discharging_efficiency[d],
                    actuator=sensor_d,
                    unit="dimensionless",
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fallback_attribute="discharging-efficiency",
                )
                .astype(float)
                .fillna(1)
            )

            roundtrip_efficiency = flex_model[d].get(
                "roundtrip_efficiency",
                sensor_d.get_attribute("roundtrip_efficiency", 1),
            )

            # if roundtrip efficiency is provided in the flex-model or defined as an asset attribute
            if "roundtrip_efficiency" in flex_model[d] or sensor_d.has_attribute(
                "roundtrip-efficiency"
            ):
                charging_efficiency[d] = roundtrip_efficiency**0.5
                discharging_efficiency[d] = roundtrip_efficiency**0.5

            device_constraints[d]["derivative down efficiency"] = (
                discharging_efficiency[d]
            )
            device_constraints[d]["derivative up efficiency"] = charging_efficiency[d]

            # Apply storage efficiency (accounts for losses over time)
            if isinstance(storage_efficiency[d], ur.Quantity) or isinstance(
                storage_efficiency[d], Sensor
            ):
                device_constraints[d]["efficiency"] = (
                    get_continuous_series_sensor_or_quantity(
                        variable_quantity=storage_efficiency[d],
                        actuator=sensor_d,
                        unit="dimensionless",
                        query_window=(start, end),
                        resolution=resolution,
                        beliefs_before=belief_time,
                        fallback_attribute="storage_efficiency",  # this should become storage-efficiency
                        max_value=1,
                    )
                    .astype(float)
                    .fillna(1.0)
                    .clip(lower=0.0, upper=1.0)
                )
            elif storage_efficiency[d] is not None:
                device_constraints[d]["efficiency"] = storage_efficiency[d]

            # check that storage constraints are fulfilled
            if not skip_validation:
                constraint_violations = validate_storage_constraints(
                    constraints=device_constraints[d],
                    soc_at_start=soc_at_start[d],
                    soc_min=soc_min[d],
                    soc_max=soc_max[d],
                    resolution=resolution,
                )

                if len(constraint_violations) > 0:
                    # TODO: include hints from constraint_violations into the error message
                    message = create_constraint_violations_message(
                        constraint_violations
                    )
                    raise ValueError(
                        "The input data yields an infeasible problem. Constraint validation has found the following issues:\n"
                        + message
                    )

        return (
            sensors,
            start,
            end,
            resolution,
            soc_at_start,
            device_constraints,
            ems_constraints,
            commitments,
        )

    def persist_flex_model(self):
        """Store new soc info as GenericAsset attributes

        This method should become obsolete when all SoC information is recorded on a sensor, instead.
        """
        if self.sensor is not None:
            self.sensor.generic_asset.set_attribute(
                "soc_datetime", self.start.isoformat()
            )
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

        self.collect_flex_config()
        self.flex_context = FlexContextSchema().load(self.flex_context)

        if isinstance(self.flex_model, dict):
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

            # Extend schedule period in case a target exceeds its end
            self.possibly_extend_end(soc_targets=self.flex_model.get("soc_targets"))
        elif isinstance(self.flex_model, list):
            # todo: ensure_soc_min_max in case the device is a storage (see line 847)
            self.flex_model = MultiSensorFlexModelSchema(many=True).load(
                self.flex_model
            )
            for d, sensor_flex_model in enumerate(self.flex_model):
                self.flex_model[d] = StorageFlexModelSchema(
                    start=self.start,
                    sensor=sensor_flex_model["sensor"],
                    default_soc_unit=sensor_flex_model["sensor_flex_model"].get(
                        "soc-unit"
                    ),
                ).load(sensor_flex_model["sensor_flex_model"])
                self.flex_model[d]["sensor"] = sensor_flex_model["sensor"]

                # Extend schedule period in case a target exceeds its end
                self.possibly_extend_end(
                    soc_targets=self.flex_model[d].get("soc_targets"),
                    sensor=self.flex_model[d]["sensor"],
                )

        else:
            raise TypeError(
                f"Unsupported type of flex-model: '{type(self.flex_model)}'"
            )

        return self.flex_model

    def possibly_extend_end(self, soc_targets, sensor: Sensor = None):
        """Extend schedule period in case a target exceeds its end.

        The schedule's duration is possibly limited by the server config setting 'FLEXMEASURES_MAX_PLANNING_HORIZON'.

        todo: when deserialize_flex_config becomes a single schema for the whole scheduler,
              this function would become a class method with a @post_load decorator.
        """
        if sensor is None:
            sensor = self.sensor

        if soc_targets and not isinstance(soc_targets, Sensor):
            max_target_datetime = max([soc_target["end"] for soc_target in soc_targets])
            if max_target_datetime > self.end:
                max_server_horizon = get_max_planning_horizon(sensor.event_resolution)
                if max_server_horizon:
                    self.end = min(max_target_datetime, self.start + max_server_horizon)
                else:
                    self.end = max_target_datetime

    def get_min_max_targets(self) -> tuple[float | None, float | None]:
        """This happens before deserializing the flex-model."""
        min_target = None
        max_target = None

        # if the SOC targets are defined as a Sensor, we don't get min max values
        if isinstance(self.flex_model.get("soc-targets"), dict):
            return None, None

        if "soc-targets" in self.flex_model and len(self.flex_model["soc-targets"]) > 0:
            min_target = min(
                [target["value"] for target in self.flex_model["soc-targets"]]
            )
            max_target = max(
                [target["value"] for target in self.flex_model["soc-targets"]]
            )
        return min_target, max_target

    def get_min_max_soc_on_sensor(self) -> tuple[float | None, float | None]:
        """This happens before deserializing the flex-model."""
        soc_min_sensor: float | None = self.sensor.get_attribute("min_soc_in_mwh")
        soc_max_sensor: float | None = self.sensor.get_attribute("max_soc_in_mwh")
        if soc_min_sensor and self.flex_model.get("soc-unit") == "kWh":
            soc_min_sensor *= 1000  # later steps assume soc data is kWh
        if soc_max_sensor and self.flex_model.get("soc-unit") == "kWh":
            soc_max_sensor *= 1000
        return soc_min_sensor, soc_max_sensor

    def ensure_soc_min_max(self):
        """
        Make sure we have min and max SOC.
        If not passed directly, then get default from sensor or targets.
        This happens before deserializing the flex-model.
        """
        _, max_target = self.get_min_max_targets()
        soc_min_sensor, soc_max_sensor = self.get_min_max_soc_on_sensor()
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

    def _get_device_power_capacity(
        self, flex_model: list[dict], sensors: list[Sensor]
    ) -> list[ur.Quantity]:
        """The device power capacity for each device must be known for the optimization problem to stay bounded.

        We search for the power capacity in the following order:
        1. Look for the power_capacity_in_mw field in the deserialized flex-model.
        2. Look for the capacity_in_mw attribute of the sensor.
        3. Look for the capacity_in_mw attribute of the asset (sensor.get_attribute does this internally).
        4. Look for the power-capacity attribute of the sensor.
        5. Look for the power-capacity attribute of the asset.
        6. Look for the site-power-capacity attribute of the asset.
        """
        power_capacities = []
        for flex_model_d, sensor in zip(flex_model, sensors):

            # 1, 2 and 3
            power_capacity_in_mw = flex_model_d.get(
                "power_capacity_in_mw",
                sensor.get_attribute("capacity_in_mw"),
            )
            if power_capacity_in_mw is not None:
                power_capacities.append(
                    self._ensure_variable_quantity(power_capacity_in_mw, "MW")
                )
                continue

            # 4 and 5
            power_capacity = sensor.get_attribute("power-capacity")
            if power_capacity is not None:
                power_capacities.append(
                    self._ensure_variable_quantity(power_capacity, "MW")
                )
                continue

            # 6
            site_power_capacity = sensor.generic_asset.get_attribute(
                "site-power-capacity"
            )
            if site_power_capacity is not None:
                current_app.logger.warning(
                    f"Missing 'power-capacity' or 'capacity_in_mw' attribute on power sensor {sensor.id}. Using site-power-capacity instead."
                )
                power_capacities.append(
                    self._ensure_variable_quantity(site_power_capacity, "MW")
                )
                continue

            raise ValueError(
                "Power capacity is not defined in the sensor attributes or the flex-model."
            )
        return power_capacities

    def _ensure_variable_quantity(
        self, value: str | int | float | ur.Quantity, unit: str
    ) -> Sensor | list[dict] | ur.Quantity:
        if isinstance(value, str):
            q = ur.Quantity(value).to(unit)
        elif isinstance(value, (float, int)):
            q = ur.Quantity(f"{value} {unit}")
        elif isinstance(value, (Sensor, list, ur.Quantity)):
            q = value
        else:
            raise TypeError(
                f"Unsupported type '{type(value)}' to describe Quantity. Value: {value}"
            )
        return q


class StorageFallbackScheduler(MetaStorageScheduler):
    __version__ = "2"
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
            sensors,
            start,
            end,
            resolution,
            soc_at_start,
            device_constraints,
            ems_constraints,
            commitments,
        ) = self._prepare(skip_validation=skip_validation)

        # Fallback policy if the problem was unsolvable
        storage_schedule = {
            sensor: fallback_charging_policy(
                sensor, device_constraints[d], start, end, resolution
            )
            for d, sensor in enumerate(sensors)
        }

        # Convert each device schedule to the unit of the device's power sensor
        storage_schedule = {
            sensor: convert_units(storage_schedule[sensor], "MW", sensor.unit)
            for sensor in sensors
        }

        # Round schedule
        if self.round_to_decimals:
            storage_schedule = {
                sensor: storage_schedule[sensor].round(self.round_to_decimals)
                for sensor in sensors
            }

        if self.return_multiple:
            return [
                {
                    "name": "storage_schedule",
                    "sensor": sensor,
                    "data": storage_schedule[sensor],
                }
                for sensor in sensors
            ]
        else:
            return storage_schedule[sensors[0]]


class StorageScheduler(MetaStorageScheduler):
    __version__ = "5"
    __author__ = "Seita"

    fallback_scheduler_class: Type[Scheduler] = StorageFallbackScheduler

    def compute(self, skip_validation: bool = False) -> SchedulerOutputType:
        """Schedule a battery or Charge Point based directly on the latest beliefs regarding market prices within the specified time window.
        For the resulting consumption schedule, consumption is defined as positive values.

        :param skip_validation: If True, skip validation of constraints specified in the data.
        :returns:               The computed schedule.
        """

        (
            sensors,
            start,
            end,
            resolution,
            soc_at_start,
            device_constraints,
            ems_constraints,
            commitments,
        ) = self._prepare(skip_validation=skip_validation)

        ems_schedule, expected_costs, scheduler_results, model = device_scheduler(
            device_constraints=device_constraints,
            ems_constraints=ems_constraints,
            commitments=commitments,
            initial_stock=[
                (
                    soc_at_start_d * (timedelta(hours=1) / resolution)
                    if soc_at_start_d is not None
                    else 0
                )
                for soc_at_start_d in soc_at_start
            ],
        )
        if scheduler_results.solver.termination_condition == "infeasible":
            raise InfeasibleProblemException()

        # Obtain the storage schedule from all device schedules within the EMS
        storage_schedule = {sensor: ems_schedule[d] for d, sensor in enumerate(sensors)}

        # Convert each device schedule to the unit of the device's power sensor
        storage_schedule = {
            sensor: convert_units(storage_schedule[sensor], "MW", sensor.unit)
            for sensor in sensors
        }

        flex_model = self.flex_model

        if not isinstance(self.flex_model, list):
            flex_model["sensor"] = sensors[0]
            flex_model = [flex_model]

        soc_schedule = {
            flex_model_d["state_of_charge"]: convert_units(
                integrate_time_series(
                    series=ems_schedule[d],
                    initial_stock=soc_at_start[d],
                    stock_delta=device_constraints[d]["stock delta"]
                    * resolution
                    / timedelta(hours=1),
                    up_efficiency=device_constraints[d]["derivative up efficiency"],
                    down_efficiency=device_constraints[d]["derivative down efficiency"],
                    storage_efficiency=device_constraints[d]["efficiency"]
                    .astype(float)
                    .fillna(1),
                ),
                from_unit="MWh",
                to_unit=flex_model_d["state_of_charge"].unit,
            )
            for d, flex_model_d in enumerate(flex_model)
            if isinstance(flex_model_d.get("state_of_charge", None), Sensor)
        }

        # Resample each device schedule to the resolution of the device's power sensor
        if self.resolution is None:
            storage_schedule = {
                sensor: storage_schedule[sensor]
                .resample(sensor.event_resolution)
                .mean()
                for sensor in sensors
            }

        # Round schedule
        if self.round_to_decimals:
            storage_schedule = {
                sensor: storage_schedule[sensor].round(self.round_to_decimals)
                for sensor in sensors
            }
            soc_schedule = {
                sensor: soc_schedule[sensor].round(self.round_to_decimals)
                for sensor in soc_schedule.keys()
            }

        if self.return_multiple:
            storage_schedules = [
                {
                    "name": "storage_schedule",
                    "sensor": sensor,
                    "data": storage_schedule[sensor],
                    "unit": sensor.unit,
                }
                for sensor in sensors
            ]
            commitment_costs = [
                {
                    "name": "commitment_costs",
                    "data": {
                        c.name: costs
                        for c, costs in zip(
                            commitments, model.commitment_costs.values()
                        )
                    },
                    "unit": self.flex_context["shared_currency_unit"],
                },
            ]
            soc_schedules = [
                {
                    "name": "state_of_charge",
                    "data": soc,
                    "sensor": sensor,
                    "unit": sensor.unit,
                }
                for sensor, soc in soc_schedule.items()
            ]
            return storage_schedules + commitment_costs + soc_schedules
        else:
            return storage_schedule[sensors[0]]


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
    Freq: 15min, dtype: float64

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
    :param resolution:                  Timedelta used to resample the constraints to the resolution of the schedule.
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

    storage_device_constraints["min"] = (
        storage_device_constraints["min"].astype(float).fillna(soc_min_change)
    )

    if soc_maxima is not None:
        storage_device_constraints["max"] = build_device_soc_values(
            soc_maxima,
            soc_at_start,
            start,
            end,
            resolution,
        )

    storage_device_constraints["max"] = (
        storage_device_constraints["max"].astype(float).fillna(soc_max_change)
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
    _constraints["min(t-1)"] = prepend_series(_constraints["min(t)"], soc_min)
    _constraints["equals(t-1)"] = prepend_series(
        _constraints["equals(t)"], soc_at_start
    )
    _constraints["max(t-1)"] = prepend_series(_constraints["max(t)"], soc_max)

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

    lhs = (
        constraints_df.astype(float)
        .fillna(0)
        .eval(lhs_expression)
        .round(round_to_decimals)
    )
    rhs = (
        constraints_df.astype(float)
        .fillna(0)
        .eval(rhs_expression)
        .round(round_to_decimals)
    )

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


def prepend_series(series: pd.Series, value) -> pd.Series:
    """Prepend a value to a time series

    :param series: series containing the timed values
    :param value: value to place in the first position
    """
    # extend max
    series = series.copy()
    # insert `value` at time `series.index[0] - resolution` which creates a new entry at the end of the series
    series[series.index[0] - series.index.freq] = value
    # sort index to keep the time ordering
    series = series.sort_index()
    return series.shift(1)


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
