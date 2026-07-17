from __future__ import annotations

import re
import copy
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
from flask import current_app
from marshmallow import ValidationError

from flexmeasures import Asset, Sensor
from flexmeasures.data import db
from flexmeasures.data.models.planning import (
    FlowCommitment,
    Scheduler,
    SchedulerOutputType,
    StockCommitment,
)
from flexmeasures.data.models.planning.devices import (
    DeviceInventory,
    _resolve_stock_key,
)
from flexmeasures.data.models.planning.linear_optimization import device_scheduler
from flexmeasures.data.models.planning.utils import (
    add_tiny_price_slope,
    ensure_prices_are_not_empty,
    initialize_index,
    initialize_series,
    initialize_df,
    get_power_values,
    get_continuous_series_sensor_or_quantity,
)
from flexmeasures.data.models.planning.exceptions import InfeasibleProblemException
from flexmeasures.data.schemas.scheduling.storage import StorageFlexModelSchema
from flexmeasures.data.schemas.scheduling import (
    CommodityFlexContextSchema,
    FlexContextSchema,
    MultiSensorFlexModelSchema,
    SharedSchema,
)
from flexmeasures.data.models.planning.soc_projection import (
    project_off_tick_soc_at_start,
    project_off_tick_soc_constraints,
)
from flexmeasures.data.schemas.scheduling.utils import (
    flex_model_has_off_tick_soc_constraints,
    get_soc_constraint_resolution,
    should_project_off_tick_soc_constraints,
)
from flexmeasures.data.schemas.sensors import SensorReference, VariableQuantityField
from flexmeasures.data.services.scheduling_result import SchedulingJobResult
from flexmeasures.utils.calculations import (
    integrate_time_series,
)
from flexmeasures.utils.time_utils import get_max_planning_horizon
from flexmeasures.utils.time_utils import determine_minimum_resampling_resolution
from flexmeasures.utils.unit_utils import ur, convert_units, units_are_convertible


storage_asset_types = ["one-way_evse", "two-way_evse", "battery", "heat-storage"]


#: Key used to store and retrieve the ``SchedulingJobResult`` in RQ job metadata
#: and in the multi-result list returned by ``StorageScheduler.compute()``.
SCHEDULING_RESULT_KEY = "scheduling_result"


class MetaStorageScheduler(Scheduler):
    """This class defines the constraints of a schedule for a storage device from the
    flex-model, flex-context, and sensor and asset attributes"""

    __version__ = None
    __author__ = "Seita"

    default_resolution = timedelta(minutes=15)

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

    def _get_commodity_contexts(self) -> dict[str, dict]:
        """Return commodity-specific flex-contexts.

        Supports the new format:

            "commodities": [
                {"commodity": "electricity", ...},
                {"commodity": "gas", ...},
            ]

        and keeps backwards compatibility with old top-level fields.
        """

        commodity_contexts = {}

        for commodity_context in self.flex_context.get("commodity_contexts", []):
            commodity = commodity_context["commodity"]
            commodity_contexts[commodity] = commodity_context

        # Backwards-compatible electricity defaults from old top-level fields.
        if "electricity" not in commodity_contexts:
            commodity_contexts["electricity"] = self.flex_context

        return commodity_contexts

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

        # Look up the device inventory: every flex-model entry (and the flex-context's
        # inflexible devices) classified once, as the single source of truth for
        # device roles and canonical device indices. Tests may bypass deserialization
        # (setting config_deserialized) with an already deserialized flex config,
        # in which case we classify it here.
        inventory = self.device_inventory
        if inventory is None:
            inventory = DeviceInventory.from_flex_config(
                self.flex_model, self.flex_context, sensor=self.sensor
            )
            self.device_inventory = inventory

        device_models = inventory.device_flex_models
        self._device_models = (
            device_models  # Store filtered model for later use in _build_soc_schedule
        )
        self.stock_models = inventory.stock_entries
        # The stock groups' device indices align with the device models
        self.stock_groups = inventory.stock_groups
        # Soft SoC constraints are attached to their stock (see StockCommitment.stock),
        # so the solver couples them to the stock group rather than to a device index.
        # Off-tick SoC relaxation scoping and starting-SoC projection also track
        # stocks (not devices), so look up each device's stock key.
        device_stock_key = {
            d: stock_key
            for stock_key, group_devices in self.stock_groups.items()
            for d in group_devices
        }

        # List the asset(s) and sensor(s) being scheduled
        sensors: list[Sensor | None] = inventory.power_sensors
        assets: list[Asset | None] = inventory.assets
        if self.asset is not None:
            if not isinstance(self.flex_model, list):
                self.flex_model = [self.flex_model]
            if resolution is None:
                # in case of no sensors with a non-instantaneous resolution, schedule with a 15-minute resolution
                resolution = determine_minimum_resampling_resolution(
                    [s.event_resolution for s in sensors if s is not None],
                    fallback_resolution=self.default_resolution,
                )

        # Work on copies of the device flex-models (aligned with the device indices,
        # unlike the unfiltered self.flex_model), so the defaults applied here don't
        # leak back into the inventory's raw entries.
        flex_model = [flex_model_d.copy() for flex_model_d in device_models]
        for flex_model_d in flex_model:
            self._default_missing_directional_capacity_to_zero(flex_model_d)
        num_flexible_devices = len(device_models)

        soc_at_start = [None] * num_flexible_devices
        soc_targets = [None] * num_flexible_devices
        soc_min = [None] * num_flexible_devices
        soc_max = [None] * num_flexible_devices
        soc_minima = [None] * num_flexible_devices
        soc_maxima = [None] * num_flexible_devices
        soc_gain = [None] * num_flexible_devices
        soc_usage = [None] * num_flexible_devices
        prefer_charging_sooner = [None] * num_flexible_devices
        prefer_curtailing_later = [None] * num_flexible_devices

        # Assign SOC constraints from stock model to the first device in each group
        for stock_id, devices in self.stock_groups.items():

            stock_model = self.stock_models.get(stock_id)

            if stock_model is None:
                continue

            d0 = devices[0]

            soc_at_start[d0] = stock_model.get("soc_at_start")
            # In multi-device mode, the soc-at-start of a stock is not resolved during deserialization
            # (unlike single-sensor mode's ensure_soc_at_start()).
            # If the stock's owning entry carries a state-of-charge sensor (or time series) but no explicit soc-at-start,
            # resolve the starting stock from it here.
            # Without this, soc_at_start stays None and the scheduler applies no stock constraints,
            # so the device could discharge more energy than its store holds.
            if soc_at_start[d0] is None:
                resolved_soc_at_start = self._resolve_stock_soc_at_start(
                    stock_model, sensor=sensors[d0], stock_key=stock_id
                )
                if resolved_soc_at_start is not None:
                    soc_at_start[d0] = resolved_soc_at_start
            soc_targets[d0] = stock_model.get("soc_targets")
            soc_min[d0] = stock_model.get("soc_min")
            soc_max[d0] = stock_model.get("soc_max")
            soc_minima[d0] = stock_model.get("soc_minima")
            soc_maxima[d0] = stock_model.get("soc_maxima")
            soc_gain[d0] = stock_model.get("soc_gain")
            soc_usage[d0] = stock_model.get("soc_usage")
            prefer_charging_sooner[d0] = stock_model.get("prefer_charging_sooner")
            prefer_curtailing_later[d0] = stock_model.get("prefer_curtailing_later")

        storage_efficiency = [
            flex_model_d.get("storage_efficiency") for flex_model_d in flex_model
        ]
        # The storage efficiency is a property of the stock, not of a connected device:
        # for shared stocks, it may be defined on the entry holding the stock's SoC
        # parameters or on a single member device, and applies to all members.
        for stock_id, stock_devices in self.stock_groups.items():
            if len(stock_devices) <= 1:
                continue
            definitions = []
            stock_model = self.stock_models.get(stock_id)
            if (
                stock_model is not None
                and stock_model.get("storage_efficiency") is not None
            ):
                definitions.append(stock_model["storage_efficiency"])
            definitions.extend(
                storage_efficiency[d]
                for d in stock_devices
                if storage_efficiency[d] is not None
            )
            if len(set(map(id, definitions))) > 1:
                raise ValueError(
                    f"Multiple flex-model entries define a storage-efficiency for the same"
                    f" stock (state-of-charge sensor {stock_id}). The storage efficiency"
                    f" is a property of the shared stock, so please define it on a single"
                    f" entry."
                )
            shared_efficiency = definitions[0] if definitions else None
            for d in stock_devices:
                storage_efficiency[d] = shared_efficiency
        consumption = [flex_model_d.get("consumption") for flex_model_d in flex_model]
        production = [flex_model_d.get("production") for flex_model_d in flex_model]
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

        # Fetch the device's power capacity (required to keep the optimization problem bounded)
        power_capacity_in_mw = self._get_device_power_capacity(
            flex_model,
            assets,
            query_window=(start, end),
            resolution=resolution,
            beliefs_before=belief_time,
        )

        # Convert to UTC before fetching time series.
        start = pd.Timestamp(start).tz_convert("UTC")
        end = pd.Timestamp(end).tz_convert("UTC")

        # Set up commitments to optimise for.
        commitments = self.convert_to_commitments(
            query_window=(start, end),
            resolution=resolution,
            beliefs_before=belief_time,
            flex_model=flex_model,
        )

        index = initialize_index(start, end, resolution)
        commitment_quantities = initialize_series(0, start, end, resolution)

        # EMS constraints are kept per commodity (one device group per commodity).
        #
        # The site-power / site-consumption / site-production capacities
        # are enforced as hard EMS-level constraints (derivative max/min). Because each
        # commodity has its own set of devices, ``ems_constraints`` is a list of
        # DataFrames and ``ems_constraint_groups`` lists the device indices each
        # DataFrame applies to. The device_scheduler then bounds the summed flow of each
        # commodity's devices separately (instead of summing across all commodities).
        #
        # The commodity-specific breach/peak penalties below remain modelled as
        # FlowCommitments on top of these hard constraints.
        ems_constraints: list[pd.DataFrame] = []
        ems_constraint_groups: list[list[int]] = []

        def device_list_series(
            devices: list[int], index: pd.DatetimeIndex
        ) -> pd.Series:
            return pd.Series([tuple(devices)] * len(index), index=index, name="device")

        # The canonical device enumeration comes from the inventory: flexible devices
        # (indices lining up with the sensors and device_constraints lists), then
        # top-level (electricity) inflexible devices, then each commodity context's
        # own inflexible devices. This is the same enumeration that
        # `_compute_commodity_aggregate_schedules` relies on.
        commodity_to_devices = inventory.commodity_to_devices

        commodity_contexts = self._get_commodity_contexts()
        price_frames_by_commodity = {}

        for commodity, devices in commodity_to_devices.items():
            # Skip commodities without any devices (e.g. no electricity devices in an
            # all-gas flex-model, or a commodity context that no device refers to):
            # they need no prices, commitments or EMS constraints, and empty device
            # groups would make the optimization problem unbounded.
            if not devices:
                continue
            commodity_devices = device_list_series(devices, index)
            commodity_context = commodity_contexts.get(commodity, {})

            # Get info from commodity_context
            consumption_price_sensor = commodity_context.get("consumption_price_sensor")
            production_price_sensor = commodity_context.get("production_price_sensor")
            consumption_price = commodity_context.get(
                "consumption_price", consumption_price_sensor
            )
            production_price = commodity_context.get(
                "production_price", production_price_sensor
            )

            if production_price is None:
                production_price = consumption_price

            if consumption_price is None:
                raise ValueError(
                    f"Missing consumption price for commodity '{commodity}'."
                )

            # Energy prices for this commodity.
            up_deviation_prices = get_continuous_series_sensor_or_quantity(
                variable_quantity=consumption_price,
                unit=self.flex_context["shared_currency_unit"] + "/MWh",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                fill_sides=True,
            ).to_frame(name="event_value")
            ensure_prices_are_not_empty(up_deviation_prices, consumption_price)

            down_deviation_prices = get_continuous_series_sensor_or_quantity(
                variable_quantity=production_price,
                unit=self.flex_context["shared_currency_unit"] + "/MWh",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                fill_sides=True,
            ).to_frame(name="event_value")
            ensure_prices_are_not_empty(down_deviation_prices, production_price)

            price_frames_by_commodity[commodity] = up_deviation_prices

            # Convert energy prices to price per MW deviation for one resolution step.
            up_price = (
                up_deviation_prices.loc[start : end - resolution]["event_value"]
                * resolution
                / pd.Timedelta("1h")
            )
            down_price = (
                down_deviation_prices.loc[start : end - resolution]["event_value"]
                * resolution
                / pd.Timedelta("1h")
            )

            commitments.append(
                FlowCommitment(
                    name=f"{commodity} net energy",
                    quantity=commitment_quantities,
                    upwards_deviation_price=up_price,
                    downwards_deviation_price=down_price,
                    commodity=commodity,
                    index=index,
                    device=commodity_devices,
                    device_group=commodity,
                )
            )

            # Commodity-specific site capacities.
            # These are not written into ems_constraints. Instead, they are added as
            # FlowCommitments that only aggregate the devices of this commodity.
            ems_power_capacity = get_continuous_series_sensor_or_quantity(
                variable_quantity=commodity_context.get("ems_power_capacity_in_mw"),
                unit="MW",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                resolve_overlaps="min",
            )

            ems_consumption_capacity = get_continuous_series_sensor_or_quantity(
                variable_quantity=commodity_context.get(
                    "ems_consumption_capacity_in_mw"
                ),
                unit="MW",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                max_value=ems_power_capacity,
                resolve_overlaps="min",
            )

            ems_production_capacity = -1 * get_continuous_series_sensor_or_quantity(
                variable_quantity=commodity_context.get(
                    "ems_production_capacity_in_mw"
                ),
                unit="MW",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                max_value=ems_power_capacity,
                resolve_overlaps="min",
            )

            # Commodity-specific peak consumption commitment.
            if commodity_context.get("ems_peak_consumption_price") is not None:
                ems_peak_consumption = get_continuous_series_sensor_or_quantity(
                    variable_quantity=commodity_context.get(
                        "ems_peak_consumption_in_mw"
                    ),
                    unit="MW",
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    max_value=np.inf,  # np.nan -> np.inf to ignore commitment if no quantity is given
                    fill_sides=True,
                )
                ems_peak_consumption_price = get_continuous_series_sensor_or_quantity(
                    variable_quantity=commodity_context.get(
                        "ems_peak_consumption_price"
                    ),
                    unit=self.flex_context["shared_currency_unit"] + "/MW",
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fill_sides=True,
                )

                commitments.append(
                    FlowCommitment(
                        name=f"{commodity} consumption peak",
                        quantity=ems_peak_consumption,
                        upwards_deviation_price=ems_peak_consumption_price,
                        _type="any",
                        index=index,
                        device=commodity_devices,
                        device_group=commodity,
                        commodity=commodity,
                    )
                )

            # Commodity-specific peak production commitment.
            if commodity_context.get("ems_peak_production_price") is not None:
                ems_peak_production = get_continuous_series_sensor_or_quantity(
                    variable_quantity=commodity_context.get(
                        "ems_peak_production_in_mw"
                    ),
                    unit="MW",
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    max_value=np.inf,  # np.nan -> np.inf to ignore commitment if no quantity is given
                    fill_sides=True,
                )
                ems_peak_production_price = get_continuous_series_sensor_or_quantity(
                    variable_quantity=commodity_context.get(
                        "ems_peak_production_price"
                    ),
                    unit=self.flex_context["shared_currency_unit"] + "/MW",
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fill_sides=True,
                )

                commitments.append(
                    FlowCommitment(
                        name=f"{commodity} production peak",
                        quantity=-ems_peak_production,  # production is negative quantity
                        # negative price because peaking in the downwards (production) direction is penalized
                        downwards_deviation_price=-ems_peak_production_price,
                        _type="any",
                        index=index,
                        device=commodity_devices,
                        device_group=commodity,
                        commodity=commodity,
                    )
                )

            # Set up capacity breach commitments and EMS capacity constraints
            ems_consumption_breach_price = commodity_context.get(
                "ems_consumption_breach_price"
            )
            ems_production_breach_price = commodity_context.get(
                "ems_production_breach_price"
            )

            # Commodity-specific site consumption breach.
            if ems_consumption_breach_price is not None:

                # Convert to Series
                any_ems_consumption_breach_price = (
                    get_continuous_series_sensor_or_quantity(
                        variable_quantity=ems_consumption_breach_price,
                        unit=self.flex_context["shared_currency_unit"] + "/MW",
                        query_window=(start, end),
                        resolution=resolution,
                        beliefs_before=belief_time,
                        fill_sides=True,
                    )
                )
                all_ems_consumption_breach_price = (
                    get_continuous_series_sensor_or_quantity(
                        variable_quantity=ems_consumption_breach_price,
                        unit=self.flex_context["shared_currency_unit"]
                        + "/MW*h",  # from EUR/MWh to EUR/MW/resolution
                        query_window=(start, end),
                        resolution=resolution,
                        beliefs_before=belief_time,
                        fill_sides=True,
                    )
                )

                commitments.append(
                    FlowCommitment(
                        name=f"{commodity} any consumption breach",
                        quantity=ems_consumption_capacity,
                        # positive price because breaching in the upwards (consumption) direction is penalized
                        upwards_deviation_price=any_ems_consumption_breach_price,
                        _type="any",
                        index=index,
                        device=commodity_devices,
                        device_group=commodity,
                        commodity=commodity,
                    )
                )

                commitments.append(
                    FlowCommitment(
                        name=f"{commodity} all consumption breaches",
                        quantity=ems_consumption_capacity,
                        # positive price because breaching in the upwards (consumption) direction is penalized
                        upwards_deviation_price=all_ems_consumption_breach_price,
                        index=index,
                        device=commodity_devices,
                        device_group=commodity,
                        commodity=commodity,
                    )
                )

            # Commodity-specific site production breach.
            if ems_production_breach_price is not None:

                # Convert to Series
                any_ems_production_breach_price = (
                    get_continuous_series_sensor_or_quantity(
                        variable_quantity=ems_production_breach_price,
                        unit=self.flex_context["shared_currency_unit"] + "/MW",
                        query_window=(start, end),
                        resolution=resolution,
                        beliefs_before=belief_time,
                        fill_sides=True,
                    )
                )
                all_ems_production_breach_price = (
                    get_continuous_series_sensor_or_quantity(
                        variable_quantity=ems_production_breach_price,
                        unit=self.flex_context["shared_currency_unit"]
                        + "/MW*h",  # from EUR/MWh to EUR/MW/resolution
                        query_window=(start, end),
                        resolution=resolution,
                        beliefs_before=belief_time,
                        fill_sides=True,
                    )
                )

                # Set up commitments DataFrame to penalize any breach
                commitments.append(
                    FlowCommitment(
                        name=f"{commodity} any production breach",
                        quantity=ems_production_capacity,
                        # negative price because breaching in the downwards (production) direction is penalized
                        downwards_deviation_price=-any_ems_production_breach_price,
                        _type="any",
                        index=index,
                        device=commodity_devices,
                        device_group=commodity,
                        commodity=commodity,
                    )
                )
                # Set up commitments DataFrame to penalize each breach
                commitments.append(
                    FlowCommitment(
                        name=f"{commodity} all production breaches",
                        quantity=ems_production_capacity,
                        # negative price because breaching in the downwards (production) direction is penalized
                        downwards_deviation_price=-all_ems_production_breach_price,
                        index=index,
                        device=commodity_devices,
                        device_group=commodity,
                        commodity=commodity,
                    )
                )

            # Hard EMS-level capacity constraint for this commodity's device group.
            # If a breach price is set, the physical power capacity is the
            # hard limit (the contracted capacity is then only softly penalised via the
            # breach commitments above); otherwise the contracted capacity itself is the
            # hard limit.
            commodity_ems_constraints = initialize_df(
                StorageScheduler.COLUMNS, start, end, resolution
            )
            if ems_consumption_breach_price is not None:
                commodity_ems_constraints["derivative max"] = ems_power_capacity
            else:
                commodity_ems_constraints["derivative max"] = ems_consumption_capacity
            if ems_production_breach_price is not None:
                commodity_ems_constraints["derivative min"] = -ems_power_capacity
            else:
                commodity_ems_constraints["derivative min"] = ems_production_capacity
            ems_constraints.append(commodity_ems_constraints)
            ems_constraint_groups.append(list(devices))

        # Keep one price frame for later preference logic.
        # The existing "prefer charging sooner" code uses `up_deviation_prices`.
        # Prefer electricity prices if available, otherwise use the first commodity price.
        if "electricity" in price_frames_by_commodity:
            up_deviation_prices = price_frames_by_commodity["electricity"]
        elif price_frames_by_commodity:
            up_deviation_prices = next(iter(price_frames_by_commodity.values()))
        else:
            raise ValueError("No commodity prices were available.")
        # Commitments per device

        # StockCommitment per device to prefer a full storage by penalizing not being full
        # This corresponds to a preference for charging now rather than later, and discharging later rather than now.
        for d, (prefer_charging_sooner_d, prefer_curtailing_later_d) in enumerate(
            zip(prefer_charging_sooner, prefer_curtailing_later)
        ):
            # Mixed-device schedules can include non-storage devices such as PV.
            # These do not have a state of charge, so there is nothing to "prefer full".
            if (
                prefer_charging_sooner_d
                and soc_max[d] is not None
                and soc_at_start[d] is not None
            ):
                tiny_price_slope = (
                    add_tiny_price_slope(
                        up_deviation_prices, "event_value", order="desc"
                    )
                    - up_deviation_prices
                )
                if prefer_curtailing_later_d:
                    # Use a tiny price slope to prefer a fuller SoC sooner rather than later, by lowering penalties later
                    penalty = tiny_price_slope
                else:
                    # Constant penalty
                    penalty = tiny_price_slope.iloc[0][0]
                commitment = StockCommitment(
                    name=f"prefer a full storage {d} sooner",
                    quantity=(soc_max[d] - soc_at_start[d])
                    * (timedelta(hours=1) / resolution),
                    upwards_deviation_price=0,
                    downwards_deviation_price=-penalty,
                    index=index,
                    device=d,
                    stock=device_stock_key.get(d),
                )
                commitments.append(commitment)

        # Set up device constraints: scheduled flexible devices for this EMS (from index 0 to D-1),
        # plus the forecasted top-level (electricity) inflexible devices, plus each commodity
        # context's own inflexible devices, in that order (the inventory's canonical order).
        device_constraints = [
            initialize_df(StorageScheduler.COLUMNS, start, end, resolution)
            for i in range(inventory.num_scheduled)
        ]
        for i, inflexible_sensor in enumerate(inventory.inflexible_sensors):
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
            asset_d = assets[d]

            # fetch SOC constraints from sensors
            if isinstance(soc_targets[d], (Sensor, SensorReference)):
                soc_targets[d] = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_targets[d],
                    unit="MWh",
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    as_instantaneous_events=True,
                    resolve_overlaps="first",
                )
                # todo: check flex-model for soc_minima_breach_price and soc_maxima_breach_price fields; if these are defined, create a StockCommitment using both prices (if only 1 price is given, still create the commitment, but only penalize one direction)
            if isinstance(soc_minima[d], (Sensor, SensorReference)):
                soc_minima[d] = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_minima[d],
                    unit="MWh",
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    as_instantaneous_events=True,
                    resolve_overlaps="max",
                )
            if isinstance(soc_maxima[d], (Sensor, SensorReference)):
                soc_maxima[d] = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_maxima[d],
                    unit="MWh",
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    as_instantaneous_events=True,
                    resolve_overlaps="min",
                )

            power_capacity_in_mw[d] = get_continuous_series_sensor_or_quantity(
                variable_quantity=power_capacity_in_mw[d],
                unit="MW",
                query_window=(start, end),
                resolution=resolution,
                beliefs_before=belief_time,
                min_value=0,  # capacities are positive by definition
                resolve_overlaps="min",
            )
            device_constraints[d]["derivative max"] = power_capacity_in_mw[d]
            device_constraints[d]["derivative min"] = -power_capacity_in_mw[d]

            if sensor_d is not None and sensor_d.get_attribute(
                "is_strictly_non_positive"
            ):
                production_capacity_d = pd.Series(
                    0, index=power_capacity_in_mw[d].index
                )
                device_constraints[d]["derivative min"] = 0
            else:
                production_capacity_d = get_continuous_series_sensor_or_quantity(
                    variable_quantity=production_capacity[d],
                    unit="MW",
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
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
                            unit=self.flex_context["shared_currency_unit"] + "/MW",
                            query_window=(start, end),
                            resolution=resolution,
                            beliefs_before=belief_time,
                            fill_sides=True,
                        )
                    )
                    all_production_breach_price = (
                        get_continuous_series_sensor_or_quantity(
                            variable_quantity=production_breach_price,
                            unit=self.flex_context["shared_currency_unit"]
                            + "/MW*h",  # from EUR/MWh to EUR/MW/resolution
                            query_window=(start, end),
                            resolution=resolution,
                            beliefs_before=belief_time,
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
            if sensor_d is not None and sensor_d.get_attribute(
                "is_strictly_non_negative"
            ):
                consumption_capacity_d = pd.Series(
                    0, index=power_capacity_in_mw[d].index
                )
                device_constraints[d]["derivative max"] = 0
            else:
                consumption_capacity_d = get_continuous_series_sensor_or_quantity(
                    variable_quantity=consumption_capacity[d],
                    unit="MW",
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
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
                            unit=self.flex_context["shared_currency_unit"] + "/MW",
                            query_window=(start, end),
                            resolution=resolution,
                            beliefs_before=belief_time,
                            fill_sides=True,
                        )
                    )
                    all_consumption_breach_price = (
                        get_continuous_series_sensor_or_quantity(
                            variable_quantity=consumption_breach_price,
                            unit=self.flex_context["shared_currency_unit"]
                            + "/MW*h",  # from EUR/MWh to EUR/MW/resolution
                            query_window=(start, end),
                            resolution=resolution,
                            beliefs_before=belief_time,
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

            # Apply round-trip efficiency evenly to charging and discharging
            charging_efficiency[d] = (
                get_continuous_series_sensor_or_quantity(
                    variable_quantity=charging_efficiency[d],
                    unit="dimensionless",
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
                )
                .astype(float)
                .fillna(1)
            )
            discharging_efficiency[d] = (
                get_continuous_series_sensor_or_quantity(
                    variable_quantity=discharging_efficiency[d],
                    unit="dimensionless",
                    query_window=(start, end),
                    resolution=resolution,
                    beliefs_before=belief_time,
                )
                .astype(float)
                .fillna(1)
            )

            roundtrip_efficiency = flex_model[d].get(
                "roundtrip_efficiency",
                asset_d.flex_model.get("roundtrip-efficiency", 1),
            )

            # if roundtrip efficiency is provided in the flex-model or defined as an asset attribute
            if (
                "roundtrip_efficiency" in flex_model[d]
                or asset_d.flex_model.get("roundtrip-efficiency") is not None
            ):
                charging_efficiency[d] = roundtrip_efficiency**0.5
                discharging_efficiency[d] = roundtrip_efficiency**0.5

            # Project off-tick point-like SoC constraints onto the scheduling ticks
            # before they are turned into soft commitments or hard constraints,
            # so that both paths consume on-tick events.
            if should_project_off_tick_soc_constraints(sensor_d):
                # A starting SoC known at an off-tick time within the first
                # scheduling interval bounds the SoC on the next tick. The timing
                # is tracked per stock; a None key covers the single-sensor case
                # where the stock key cannot be resolved at record time.
                soc_at_start_datetimes = getattr(self, "soc_at_start_datetimes", {})
                soc_at_start_time = soc_at_start_datetimes.get(device_stock_key.get(d))
                if soc_at_start_time is None:
                    soc_at_start_time = soc_at_start_datetimes.get(None)
                if soc_at_start_time is not None and soc_at_start[d] is not None:
                    soc_maxima[d], soc_minima[d] = project_off_tick_soc_at_start(
                        soc_at_start_time,
                        soc_at_start[d],
                        soc_maxima[d],
                        soc_minima[d],
                        start,
                        consumption_capacity_d,
                        production_capacity_d,
                        resolution,
                        soc_min[d],
                        soc_max[d],
                        charging_efficiency=charging_efficiency[d],
                        discharging_efficiency=discharging_efficiency[d],
                    )
                (
                    soc_targets[d],
                    soc_maxima[d],
                    soc_minima[d],
                ) = project_off_tick_soc_constraints(
                    soc_targets[d],
                    soc_maxima[d],
                    soc_minima[d],
                    consumption_capacity_d,
                    production_capacity_d,
                    resolution,
                    soc_min[d],
                    soc_max[d],
                    charging_efficiency=charging_efficiency[d],
                    discharging_efficiency=discharging_efficiency[d],
                )

            if (
                self.flex_context.get("soc_minima_breach_price") is not None
                and soc_minima[d] is not None
                and self._soc_relaxation_applies_to(device_stock_key.get(d), sensor_d)
            ):
                soc_minima_breach_price = self.flex_context["soc_minima_breach_price"]
                any_soc_minima_breach_price = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_minima_breach_price,
                    unit=self.flex_context["shared_currency_unit"] + "/MWh",
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fill_sides=True,
                ).shift(-1, freq=resolution)
                all_soc_minima_breach_price = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_minima_breach_price,
                    unit=self.flex_context["shared_currency_unit"]
                    + "/MWh*h",  # from EUR/MWh² to EUR/MWh/resolution
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fill_sides=True,
                ).shift(-1, freq=resolution)
                # Set up commitments DataFrame
                # soc_minima_d is a temp variable because add_storage_constraints can't deal with Series yet
                soc_minima_d = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_minima[d],
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
                    stock=device_stock_key.get(d),
                )
                commitments.append(commitment)

                commitment = StockCommitment(
                    name="all soc minima",
                    quantity=soc_minima_d,
                    # negative price because breaching in the downwards (shortage) direction is penalized
                    downwards_deviation_price=-all_soc_minima_breach_price,
                    index=index,
                    device=d,
                    stock=device_stock_key.get(d),
                )
                commitments.append(commitment)

                # soc-minima will become a soft constraint (modelled as stock commitments), so remove hard constraint
                soc_minima[d] = None

            if (
                self.flex_context.get("soc_maxima_breach_price") is not None
                and soc_maxima[d] is not None
                and self._soc_relaxation_applies_to(device_stock_key.get(d), sensor_d)
            ):
                soc_maxima_breach_price = self.flex_context["soc_maxima_breach_price"]
                any_soc_maxima_breach_price = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_maxima_breach_price,
                    unit=self.flex_context["shared_currency_unit"] + "/MWh",
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fill_sides=True,
                ).shift(-1, freq=resolution)
                all_soc_maxima_breach_price = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_maxima_breach_price,
                    unit=self.flex_context["shared_currency_unit"]
                    + "/MWh*h",  # from EUR/MWh² to EUR/MWh/resolution
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=belief_time,
                    fill_sides=True,
                ).shift(-1, freq=resolution)
                # Set up commitments DataFrame
                # soc_maxima_d is a temp variable because add_storage_constraints can't deal with Series yet
                soc_maxima_d = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_maxima[d],
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
                    stock=device_stock_key.get(d),
                )
                commitments.append(commitment)

                commitment = StockCommitment(
                    name="all soc maxima",
                    quantity=soc_maxima_d,
                    # positive price because breaching in the upwards (surplus) direction is penalized
                    upwards_deviation_price=all_soc_maxima_breach_price,
                    index=index,
                    device=d,
                    stock=device_stock_key.get(d),
                )
                commitments.append(commitment)

                # soc-maxima will become a soft constraint (modelled as stock commitments), so remove hard constraint
                soc_maxima[d] = None

            # only apply SOC constraints to the first device of a shared stock
            apply_soc_constraints = True
            for stock_id, devices in self.stock_groups.items():
                if d in devices and d != devices[0]:
                    apply_soc_constraints = False
                    break

            if soc_at_start[d] is not None and apply_soc_constraints:
                storage_constraints = add_storage_constraints(
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
                for column in ("equals", "min", "max"):
                    device_constraints[d][column] = storage_constraints[column]
            else:
                # No need to validate non-existing storage constraints
                skip_validation = True

            all_stock_delta = []

            for is_usage, soc_delta in zip([False, True], [soc_gain[d], soc_usage[d]]):
                if soc_delta is None:
                    # Try to get fallback
                    soc_delta = [None]

                for component in soc_delta:
                    stock_delta_series = get_continuous_series_sensor_or_quantity(
                        variable_quantity=component,
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

                device_constraints[d]["stock delta"] = all_stock_delta.sum(1)
                device_constraints[d]["stock delta"] *= timedelta(hours=1) / resolution

            device_constraints[d]["derivative down efficiency"] = (
                discharging_efficiency[d]
            )
            device_constraints[d]["derivative up efficiency"] = charging_efficiency[d]

            # Apply storage efficiency (accounts for losses over time)
            if isinstance(
                storage_efficiency[d], (ur.Quantity, Sensor, SensorReference)
            ):
                device_constraints[d]["efficiency"] = (
                    get_continuous_series_sensor_or_quantity(
                        variable_quantity=storage_efficiency[d],
                        unit="dimensionless",
                        query_window=(start, end),
                        resolution=resolution,
                        beliefs_before=belief_time,
                        max_value=1,
                    )
                    .astype(float)
                    .fillna(1.0)
                    .clip(lower=0.0, upper=1.0)
                )
            elif storage_efficiency[d] is not None:
                device_constraints[d]["efficiency"] = storage_efficiency[d]

            # Convert efficiency from sensor resolution to scheduling resolution
            if device_constraints[d]["efficiency"].dropna().eq(1).all():
                # Only missing or unit efficiency; no resampling needed.
                pass
            elif isinstance(storage_efficiency[d], (Sensor, SensorReference)):
                # Resample from the resolution of the storage-efficiency sensor
                device_constraints[d]["efficiency"] **= (
                    resolution / storage_efficiency[d].event_resolution
                )
            elif sensor_d is not None and sensor_d.event_resolution != timedelta(0):
                # Resample from the resolution of the power sensor
                device_constraints[d]["efficiency"] **= (
                    resolution / sensor_d.event_resolution
                )
            elif isinstance(consumption[d], (Sensor, SensorReference)) and consumption[
                d
            ].event_resolution != timedelta(0):
                # Resample from the resolution of the consumption sensor
                device_constraints[d]["efficiency"] **= (
                    resolution / consumption[d].event_resolution
                )
            elif isinstance(production[d], (Sensor, SensorReference)) and production[
                d
            ].event_resolution != timedelta(0):
                # Resample from the resolution of the production sensor
                device_constraints[d]["efficiency"] **= (
                    resolution / production[d].event_resolution
                )
            else:
                raise ValueError(
                    "The storage-efficiency cannot be interpreted without a resolution. "
                    "Record the storage-efficiency on a sensor instead (with a non-zero resolution) and then reference that sensor in the flex-model. "
                    "Alternatively, set the consumption or production field in the flex-model to reference a sensor, "
                    "and the scheduler will assume their resolution is the one to use.",
                )

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

        # --- apply shared stock groups
        # Store original stock_delta values for use in _build_soc_schedule
        original_stock_deltas = [
            device_constraints[d]["stock delta"].copy()
            for d in range(len(device_constraints))
        ]

        if hasattr(self, "stock_groups") and self.stock_groups:
            for stock_id, devices in self.stock_groups.items():

                if len(devices) <= 1:
                    continue

                d0 = devices[0]

                # Combine all stock_deltas on the primary device
                # This ensures the optimizer sees a single shared stock
                combined_delta = sum(
                    device_constraints[d]["stock delta"] for d in devices
                )
                device_constraints[d0]["stock delta"] = combined_delta

                # Secondary devices: zero out stock_delta (it's now in primary) but keep power contribution
                for d in devices[1:]:
                    # Zero out stock_delta since it's now in primary device's combined_delta
                    device_constraints[d]["stock delta"] = 0

                    # disable stock bounds for secondary devices
                    device_constraints[d]["equals"] = np.nan
                    device_constraints[d]["min"] = np.nan
                    device_constraints[d]["max"] = np.nan

        # Store original stock_deltas for use in _build_soc_schedule
        self.original_stock_deltas = original_stock_deltas
        # Device indices each EMS constraint DataFrame applies to (one group per commodity).
        self.ems_constraint_groups = ems_constraint_groups
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

    def convert_to_commitments(
        self,
        flex_model,
        **timing_kwargs,
    ) -> list[FlowCommitment | StockCommitment]:
        """Convert list of commitment specifications (dicts) to a list of FlowCommitments."""
        commitment_specs = self.flex_context.get("commitments", [])
        if len(commitment_specs) == 0:
            return []

        start, end = timing_kwargs["query_window"]
        price_unit = self.flex_context["shared_currency_unit"] + "/MW"
        commitments = []
        for commitment_spec in commitment_specs:
            # Convert baseline, up_price and down_price to pd.Series, then create FlowCommitment
            if "up_price" in commitment_spec:
                commitment_spec["upwards_deviation_price"] = (
                    get_continuous_series_sensor_or_quantity(
                        variable_quantity=commitment_spec.pop("up_price"),
                        unit=price_unit,
                        **timing_kwargs,
                    )
                )
            if "down_price" in commitment_spec:
                commitment_spec["downwards_deviation_price"] = (
                    get_continuous_series_sensor_or_quantity(
                        variable_quantity=commitment_spec.pop("down_price"),
                        unit=price_unit,
                        **timing_kwargs,
                    )
                )
            if "baseline" in commitment_spec:
                commitment_spec["quantity"] = get_continuous_series_sensor_or_quantity(
                    variable_quantity=commitment_spec.pop("baseline"),
                    unit="MW",
                    **timing_kwargs,
                )
            commitment_spec["index"] = initialize_index(
                start, end, timing_kwargs["resolution"]
            )
            commitment_commodity = commitment_spec.get("commodity", "electricity")
            bound_device_count = 0
            for d, flex_model_d in enumerate(flex_model):
                device_commodity = flex_model_d.get("commodity", "electricity")
                if device_commodity != commitment_commodity:
                    continue
                commitment = FlowCommitment(
                    device=d,
                    device_group=device_commodity,
                    **commitment_spec,
                )
                commitments.append(commitment)
                bound_device_count += 1
            if bound_device_count == 0:
                current_app.logger.warning(
                    f"Commitment '{commitment_spec.get('name')}' has commodity"
                    f" '{commitment_commodity}', which matches none of the devices"
                    " in the flex-model. This commitment will not bind any device"
                    " (check for a typo in the commitment's `commodity` field, or in"
                    " a device's `commodity` field in the flex-model)."
                )

        return commitments

    def persist_flex_model(self):
        """Store new soc info as GenericAsset attributes

        This method should become obsolete when all SoC information is recorded on a sensor, instead.

        Deprecated: get rid of this when moving to v1.0 (requiring to also remove attributes from test data assets)
        """
        if self.sensor is not None:
            self.sensor.generic_asset.set_attribute(
                "soc_datetime", self.start.isoformat()
            )
            self.sensor.generic_asset.set_attribute(
                "soc_in_mwh", self.flex_model.get("soc_at_start")
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
        if self.flex_context is None:
            self.flex_context = {}
        #: Stock keys of stocks whose off-tick SoC constraints triggered automatic
        #: relaxation (None marks an entry whose stock key cannot be resolved from
        #: its serialized form, e.g. a state-of-charge time series).
        self.off_tick_stock_keys: set = set()
        #: Whether SoC constraint softening should apply only to those devices
        #: (True when relaxation was enabled purely because of off-tick projection).
        self.scope_soc_relaxation_to_off_tick_devices: bool = False
        # The flex-model is deserialized first, because off-tick SoC constraints
        # may enable relax-soc-constraints on the still-serialized flex-context.
        self._deserialize_flex_model()
        self._deserialize_flex_context()

        # Classify all flex-model entries (and the flex-context's inflexible devices)
        # once; scheduling and result mapping rely on this inventory for device
        # identity and canonical device indices.
        self.device_inventory = DeviceInventory.from_flex_config(
            self.flex_model, self.flex_context, sensor=self.sensor
        )

    def _deserialize_flex_context(self):
        if isinstance(self.flex_context, dict):
            # Load the one flex-context for electricity
            self.flex_context = FlexContextSchema().load(self.flex_context)
        elif isinstance(self.flex_context, list):
            # Load each flex-context per commodity
            for g, commodity_flex_context in enumerate(self.flex_context):
                self.flex_context[g] = CommodityFlexContextSchema().load(
                    commodity_flex_context
                )

            # Ensure all flex-contexts share the same currency unit. Contexts with
            # no user-given price fields at all (shared_currency_unit_is_default)
            # only carry a fallback "EUR" currency, which isn't a real constraint,
            # so they're skipped here and instead backfilled below, once a real
            # portfolio currency is known.
            shared_currency_unit = None
            default_currency_contexts = []
            for commodity_flex_context in self.flex_context:
                if commodity_flex_context.get("shared_currency_unit_is_default"):
                    default_currency_contexts.append(commodity_flex_context)
                    continue
                context_currency_unit = commodity_flex_context["shared_currency_unit"]
                if shared_currency_unit is None:
                    shared_currency_unit = context_currency_unit
                elif not units_are_convertible(
                    context_currency_unit, shared_currency_unit
                ):
                    raise ValidationError(
                        f"All prices in the flex-context must share the same currency unit (in this case: '{shared_currency_unit}')."
                    )

            # Let price-free contexts inherit the portfolio's actual currency,
            # where determinable (i.e. when at least one other context set one).
            if shared_currency_unit is not None:
                for commodity_flex_context in default_currency_contexts:
                    SharedSchema._rebase_default_context_currency(
                        commodity_flex_context, shared_currency_unit
                    )
            elif default_currency_contexts:
                # No context anywhere gave an explicit price: fall back to the
                # (shared) default currency already stamped on each of them.
                shared_currency_unit = default_currency_contexts[0][
                    "shared_currency_unit"
                ]

            # Nest the flex-contexts per commodity under the commodity_contexts field
            self.flex_context = dict(
                commodity_contexts=self.flex_context,
                shared_currency_unit=shared_currency_unit,
            )
        else:
            raise TypeError(
                f"Unsupported type of flex-context: '{type(self.flex_context)}'"
            )

    def _deserialize_flex_model(self):
        if isinstance(self.flex_model, dict):
            if self.sensor.generic_asset.asset_type.name in storage_asset_types:
                self.ensure_soc_at_start()

            self._possibly_relax_off_tick_soc_constraints(
                self.flex_model, sensor=self.sensor, power_sensor=self.sensor
            )

            # Now it's time to check if our flex configuration holds up to schemas
            schema = StorageFlexModelSchema(
                start=self.start,
                sensor=self.sensor,
                default_soc_unit=self.flex_model.get("soc-unit"),
            )
            self.flex_model = schema.load(self.flex_model)

            # Extend schedule period in case a target exceeds its end
            self.possibly_extend_end(soc_targets=self.flex_model.get("soc_targets"))
        elif isinstance(self.flex_model, list):
            self.flex_model = MultiSensorFlexModelSchema(many=True).load(
                self.flex_model
            )
            for d, sensor_flex_model in enumerate(self.flex_model):
                soc_sensor_id = (
                    sensor_flex_model["sensor_flex_model"]
                    .get("state-of-charge", {})
                    .get("sensor", None)
                )
                soc_sensor = None
                if soc_sensor_id is not None:
                    soc_sensor = Sensor.query.filter_by(id=soc_sensor_id).first()
                sensor_d = (
                    sensor_flex_model.get("sensor")
                    if sensor_flex_model.get("sensor") is not None
                    else soc_sensor
                )
                self._possibly_relax_off_tick_soc_constraints(
                    sensor_flex_model["sensor_flex_model"],
                    sensor=sensor_d,
                    power_sensor=sensor_flex_model.get("sensor"),
                )
                schema = StorageFlexModelSchema(
                    start=self.start,
                    sensor=sensor_d,
                    default_soc_unit=sensor_flex_model["sensor_flex_model"].get(
                        "soc-unit"
                    ),
                )
                self.flex_model[d] = schema.load(sensor_flex_model["sensor_flex_model"])
                self.flex_model[d]["sensor"] = sensor_flex_model.get("sensor")
                self.flex_model[d]["asset"] = sensor_flex_model.get("asset")

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

    def _possibly_relax_off_tick_soc_constraints(
        self,
        flex_model: dict,
        sensor: Sensor | None,
        power_sensor: Sensor | None = None,
    ) -> None:
        """Enable SoC constraint relaxation if the (serialized) flex-model contains off-tick SoC events.

        The detection uses the scheduler's actual resolution (falling back to the
        sensor's event resolution), matching the resolution later used to project
        off-tick SoC constraints onto the scheduling ticks.

        When relaxation is enabled purely because of off-tick projection (rather
        than by the user's own flex-context settings), softening is scoped to the
        stocks that actually use off-tick SoC constraints (tracked here by their
        stock key, so all devices sharing the stock are covered). An entry without
        a resolvable stock key is tracked by its power sensor instead (its stock
        gets a synthetic key only later, when the device inventory is built).
        """
        if not should_project_off_tick_soc_constraints(sensor):
            return
        resolution = get_soc_constraint_resolution(
            self.resolution, sensor, self.default_resolution
        )
        if flex_model_has_off_tick_soc_constraints(flex_model, resolution=resolution):
            stock_key = _resolve_stock_key(flex_model.get("state-of-charge"))
            if stock_key is None and power_sensor is not None:
                stock_key = ("sensor", power_sensor.id)
            self.off_tick_stock_keys.add(stock_key)
            self.scope_soc_relaxation_to_off_tick_devices = (
                not self._soc_relaxation_user_enabled()
            )
            self.enable_relax_soc_constraints()

    def _soc_relaxation_user_enabled(self) -> bool:
        """Whether the user's own (serialized) flex-context already softens SoC constraints.

        That is the case when any context defines a SoC breach price explicitly,
        sets ``relax-soc-constraints`` to ``True``, or leaves relaxation to the
        general ``relax-constraints`` flag (which defaults to ``True``).
        """
        if isinstance(self.flex_context, dict):
            contexts = [self.flex_context] + list(
                self.flex_context.get("commodities", [])
            )
        elif isinstance(self.flex_context, list):
            contexts = self.flex_context
        else:
            return True
        for context in contexts:
            if (
                context.get("soc-minima-breach-price") is not None
                or context.get("soc-maxima-breach-price") is not None
            ):
                return True
            if context.get("relax-soc-constraints") is True:
                return True
            if context.get("relax-soc-constraints") is None and context.get(
                "relax-constraints", True
            ):
                return True
        return False

    def _soc_relaxation_applies_to(
        self, stock_key, sensor_d: Sensor | None = None
    ) -> bool:
        """Whether SoC constraint softening applies to the stock with this key.

        Softening applies to all stocks, unless relaxation was auto-enabled purely
        for off-tick SoC constraint projection, in which case it is scoped to the
        stocks that use off-tick SoC constraints (covering all devices sharing them).
        A stock tracked by power sensor (for lack of a resolvable stock key) is
        matched via the device's power sensor.
        """
        if not getattr(self, "scope_soc_relaxation_to_off_tick_devices", False):
            return True
        off_tick_stock_keys = getattr(self, "off_tick_stock_keys", set())
        if None in off_tick_stock_keys:
            # An entry with neither a resolvable stock key nor a power sensor
            # cannot be matched to a stock.
            return True
        if stock_key is not None and stock_key in off_tick_stock_keys:
            return True
        return sensor_d is not None and ("sensor", sensor_d.id) in off_tick_stock_keys

    def enable_relax_soc_constraints(self) -> None:
        """Relax SoC constraints when off-tick SoC events require scheduling-tick projection.

        Projection can add bounds (and stricter combinations of bounds), which could
        render the problem infeasible if they remain hard constraints. Therefore,
        ``relax-soc-constraints`` is enabled unless the user explicitly disabled it,
        in which case we respect that choice and only log a warning.
        """

        def _enable(context: dict) -> None:
            if context.get("relax-soc-constraints") is False:
                current_app.logger.warning(
                    "Off-tick SoC constraints are projected onto the scheduling ticks, "
                    "which can add bounds that render the scheduling problem infeasible, "
                    "but 'relax-soc-constraints' is explicitly disabled. "
                    "Keeping SoC constraints hard."
                )
                return
            if context.get("relax-soc-constraints") is not True:
                current_app.logger.info(
                    "Enabling 'relax-soc-constraints' because off-tick SoC constraints "
                    "are projected onto the scheduling ticks."
                )
            context["relax-soc-constraints"] = True

        if self.flex_context is None:
            self.flex_context = {}
        if isinstance(self.flex_context, dict):
            _enable(self.flex_context)
            for commodity_context in self.flex_context.get("commodities", []):
                _enable(commodity_context)
            return
        if isinstance(self.flex_context, list):
            for commodity_context in self.flex_context:
                _enable(commodity_context)

    def has_soc_at_start(self) -> bool:
        return (
            "soc-at-start" in self.flex_model
            and self.flex_model["soc-at-start"] is not None
        )

    @staticmethod
    def has_soc_at_start_in(flex_model: dict) -> bool:
        return "soc-at-start" in flex_model and flex_model["soc-at-start"] is not None

    def _record_soc_at_start_datetime(
        self, stock_key, soc_datetime: datetime | None
    ) -> None:
        """Remember at which time a stock's starting state of charge is actually known.

        Keyed by the stock key (a None key covers the single-sensor case where the
        stock key cannot be resolved, e.g. a state-of-charge time series). Used to
        project an off-tick starting SoC onto the next scheduling tick (see
        :func:`flexmeasures.data.models.planning.soc_projection.project_off_tick_soc_at_start`).
        """
        if soc_datetime is None:
            return
        if not hasattr(self, "soc_at_start_datetimes"):
            self.soc_at_start_datetimes: dict = {}
        self.soc_at_start_datetimes[stock_key] = soc_datetime

    def _get_soc_lookup_radius(
        self, sensor: Sensor | None = None, slack_steps: int = 4
    ) -> timedelta:
        """Return the half-width of the SoC lookup interval.

        We search for a nearby SoC value in the interval
        ``[self.start - slack_steps * resolution, self.start + slack_steps * resolution]``.
        Using four resolution steps by default keeps the lookup tolerant to small timing
        offsets while still rejecting stale values. For example, a 15-minute
        resolution yields a 1-hour lookup radius.

        :param sensor:      Optional sensor whose resolution should be used.
        :param slack_steps: Number of resolution steps accepted on either side of
                            the schedule start.
        :returns:           Half-width of the SoC lookup interval.
        """
        resolution = self.resolution
        if resolution is None and sensor is not None:
            resolution = sensor.event_resolution
        if resolution is None:
            resolution = self.default_resolution
        return slack_steps * resolution

    def _get_soc_capacity_for_percent_conversion(
        self, flex_model: dict, sensor: Sensor | None = None
    ) -> str:
        """Return the capacity used to convert percentage-based SoC values.

        :param flex_model: Flex model containing the SoC configuration.
        :param sensor:     Optional scheduled power sensor whose asset can provide fallback capacity.
        :returns:          Capacity expressed in MWh.
        """
        soc_max = flex_model.get("soc-max")
        soc_unit = flex_model.get("soc-unit")
        capacity_sensor = sensor or self.sensor
        if soc_max is None and capacity_sensor is not None:
            soc_max = capacity_sensor.generic_asset.flex_model.get("soc-max")
        if soc_max is None and capacity_sensor is not None:
            soc_max = capacity_sensor.generic_asset.get_attribute("max_soc_in_mwh")
        if soc_max is None:
            raise ValueError(
                "Cannot derive state of charge from a `state-of-charge` sensor with '%' unit without `soc-max`."
            )
        if isinstance(soc_max, (Sensor, SensorReference)):
            raise ValueError(
                "Cannot derive state of charge from a `state-of-charge` sensor with '%' unit when `soc-max` is a sensor reference."
            )
        if isinstance(soc_max, (int, float)):
            return str(ur.Quantity(soc_max, soc_unit).to("MWh"))
        return str(ur.Quantity(soc_max).to("MWh"))

    def _convert_soc_value_to_mwh(
        self,
        value: float,
        from_unit: str,
        flex_model: dict,
        sensor: Sensor | None = None,
    ) -> float:
        capacity = (
            self._get_soc_capacity_for_percent_conversion(flex_model, sensor)
            if from_unit == "%"
            else None
        )
        return convert_units(
            data=value,
            from_unit=from_unit,
            to_unit="MWh",
            capacity=capacity,
        )

    def _resolve_soc_at_start_from_sensor(
        self,
        state_of_charge_sensor: Sensor | SensorReference,
        flex_model: dict,
        sensor: Sensor | None = None,
    ) -> float:
        """Resolve ``soc-at-start`` from a ``state-of-charge`` sensor.

        :param state_of_charge_sensor: Instantaneous SoC sensor or sensor reference (with optional source filters).
        :param flex_model:             Flex model containing the SoC configuration.
        :param sensor:                 Optional scheduled power sensor.
        :returns:                      Starting SoC in MWh.
        """
        # Unpack SensorReference to extract the underlying sensor and any source filters.
        if isinstance(state_of_charge_sensor, SensorReference):
            source_types = state_of_charge_sensor.source_types
            exclude_source_types = state_of_charge_sensor.exclude_source_types
            sources = state_of_charge_sensor.sources
            source_account_ids = (
                [a.id for a in state_of_charge_sensor.source_account]
                if state_of_charge_sensor.source_account
                else None
            )
            soc_sensor = state_of_charge_sensor.sensor
        else:
            source_types = None
            exclude_source_types = None
            sources = None
            source_account_ids = None
            soc_sensor = state_of_charge_sensor

        lookup_radius = self._get_soc_lookup_radius(sensor)
        beliefs = soc_sensor.search_beliefs(
            event_starts_after=self.start - lookup_radius,
            event_ends_before=self.start + lookup_radius,
            one_deterministic_belief_per_event=True,
            source_types=source_types,
            exclude_source_types=exclude_source_types,
            source=sources,
            source_account_ids=source_account_ids,
        )
        if beliefs.empty:
            raise ValueError(
                f"No recent state-of-charge value found for sensor {soc_sensor.id} "
                f"within {lookup_radius} of schedule start {self.start.isoformat()}."
            )

        beliefs_df = beliefs.reset_index()
        beliefs_df["time_distance"] = (
            beliefs_df["event_start"] - pd.Timestamp(self.start)
        ).abs()
        nearest_beliefs = beliefs_df[
            beliefs_df["time_distance"] == beliefs_df["time_distance"].min()
        ]
        nearest_belief = nearest_beliefs.loc[nearest_beliefs["event_start"].idxmax()]
        self._record_soc_at_start_datetime(soc_sensor.id, nearest_belief["event_start"])

        return self._convert_soc_value_to_mwh(
            value=nearest_belief["event_value"],
            from_unit=soc_sensor.unit,
            flex_model=flex_model,
            sensor=sensor,
        )

    def _resolve_soc_at_start_from_time_series(
        self, soc_time_series: list[dict], sensor: Sensor | None = None, stock_key=None
    ) -> float:
        """Resolve ``soc-at-start`` from a ``state-of-charge`` time series.

        :param soc_time_series: SoC time series specification.
        :param sensor:          Optional scheduled power sensor.
        :param stock_key:       Key of the stock whose SoC is being resolved, if known
                                (a time series does not resolve to a stock key by itself).
        :returns:               Starting SoC in MWh.
        """
        lookup_radius = self._get_soc_lookup_radius(sensor)
        normalized_segments = [
            {
                "start": pd.Timestamp(segment["start"]),
                "end": pd.Timestamp(segment["end"]),
                "value": ur.Quantity(segment["value"]).to("MWh"),
            }
            for segment in soc_time_series
        ]
        matching_segments = [
            segment
            for segment in normalized_segments
            if segment["start"] <= self.start < segment["end"]
        ]
        if matching_segments:
            latest_matching_segment = max(
                matching_segments, key=lambda segment: segment["start"]
            )
            return (latest_matching_segment["value"] / ur.Quantity("MWh")).magnitude

        candidate_segments = []
        for segment in normalized_segments:
            start_distance = abs(segment["start"] - self.start)
            end_distance = abs(segment["end"] - self.start)
            distance = min(start_distance, end_distance)
            if distance <= lookup_radius:
                candidate_segments.append((distance, segment))

        if not candidate_segments:
            raise ValueError(
                f"No recent state-of-charge value found in the provided `state-of-charge` time series "
                f"within {lookup_radius} of schedule start {self.start.isoformat()}."
            )

        _, nearest_segment = min(candidate_segments, key=lambda item: item[0])
        self._record_soc_at_start_datetime(stock_key, nearest_segment["start"])
        return (nearest_segment["value"] / ur.Quantity("MWh")).magnitude

    def _resolve_soc_at_start_from_state_of_charge(
        self, flex_model: dict, sensor: Sensor | None = None
    ) -> float | None:
        """Resolve ``soc-at-start`` from the ``state-of-charge`` field.

        :param flex_model: Flex model containing the SoC configuration.
        :param sensor:     Optional scheduled power sensor.
        :returns:          Starting SoC in MWh if it can be inferred.
        """
        state_of_charge = flex_model.get("state-of-charge")
        if isinstance(state_of_charge, SensorReference):
            return self._resolve_soc_at_start_from_sensor(
                state_of_charge, flex_model, sensor
            )
        if isinstance(state_of_charge, Sensor):
            return self._resolve_soc_at_start_from_sensor(
                state_of_charge, flex_model, sensor
            )
        if isinstance(state_of_charge, list):
            return self._resolve_soc_at_start_from_time_series(state_of_charge, sensor)
        if isinstance(state_of_charge, dict) and "sensor" in state_of_charge:
            sensor_id = (
                state_of_charge["sensor"].id
                if isinstance(state_of_charge["sensor"], Sensor)
                else state_of_charge["sensor"]
            )
            state_of_charge_sensor = db.session.get(Sensor, sensor_id)
            if state_of_charge_sensor is None:
                raise ValueError(
                    f"State-of-charge sensor with id {sensor_id} was not found."
                )
            source_filter_keys = {
                "source-types",
                "exclude-source-types",
                "sources",
                "source-account",
            }
            if not source_filter_keys.isdisjoint(state_of_charge.keys()):
                state_of_charge_sensor = VariableQuantityField(
                    to_unit="MWh",
                    return_magnitude=False,
                    additional_sensor_units=["%"],
                ).deserialize({**state_of_charge, "sensor": sensor_id})
            return self._resolve_soc_at_start_from_sensor(
                state_of_charge_sensor, flex_model, sensor
            )
        return None

    def _resolve_stock_soc_at_start(
        self, stock_model: dict, sensor: Sensor | None = None, stock_key=None
    ) -> float | None:
        """Resolve a stock's soc-at-start (in MWh) from its (deserialized) state-of-charge.

        Used in multi-device mode, where soc-at-start is not resolved during deserialization.
        Operates on the deserialized stock-owning entry,
        whose ``state_of_charge`` is a :class:`Sensor`, :class:`SensorReference` or time series.

        In line with single-sensor mode's ``ensure_soc_at_start()``,
        a state of charge that is given but cannot be resolved fails the schedule:
        a ``ValueError`` is raised, e.g. for a state-of-charge sensor without a recent value.

        :param stock_model: The deserialized flex-model entry owning the stock's SoC parameters.
        :param sensor:      The stock's (first) device power sensor, used for the SoC lookup radius.
        :returns:           Starting stock in MWh, or None if the entry defines no state of charge.
        """
        state_of_charge = stock_model.get("state_of_charge")
        if isinstance(state_of_charge, (Sensor, SensorReference)):
            # The percent-conversion helpers expect a pre-deserialization (hyphenated) flex model,
            # while the stock-owning entry is already deserialized (underscored keys, values in MWh).
            percent_conversion_model = {
                "soc-max": stock_model.get("soc_max"),
                "soc-unit": "MWh",
            }
            return self._resolve_soc_at_start_from_sensor(
                state_of_charge, percent_conversion_model, sensor
            )
        if isinstance(state_of_charge, list):
            return self._resolve_soc_at_start_from_time_series(
                state_of_charge, sensor, stock_key=stock_key
            )
        return None

    def possibly_extend_end(self, soc_targets, sensor: Sensor = None):
        """Extend schedule period in case a target exceeds its end.

        The schedule's duration is possibly limited by the server config setting 'FLEXMEASURES_MAX_PLANNING_HORIZON'.

        todo: when deserialize_flex_config becomes a single schema for the whole scheduler,
              this function would become a class method with a @post_load decorator.
        """
        if sensor is None:
            sensor = self.sensor
            # todo: what if self.sensor is None, too

        if soc_targets and not isinstance(soc_targets, (Sensor, SensorReference)):
            max_target_datetime = max([soc_target["end"] for soc_target in soc_targets])
            # Off-tick target times are preserved during deserialization, and their
            # projection moves the target to the next scheduling tick. Ceil to the
            # scheduling resolution, so the projected target still falls within the
            # schedule (instead of being disregarded as beyond its end).
            resolution = self.resolution or sensor.event_resolution
            if resolution not in (None, timedelta(0)):
                max_target_datetime = (
                    pd.Timestamp(max_target_datetime).ceil(resolution).to_pydatetime()
                )
            if max_target_datetime > self.end:
                max_server_horizon = get_max_planning_horizon(sensor.event_resolution)
                if max_server_horizon:
                    self.end = min(max_target_datetime, self.start + max_server_horizon)
                else:
                    self.end = max_target_datetime

    def ensure_soc_at_start(
        self, flex_model: dict | None = None, sensor: Sensor | None = None
    ) -> dict:
        """
        Ensure we have a starting state of charge - if needed.
        Preferably, a starting soc is given.
        Otherwise, we try to retrieve the current state of charge from the configured ``state-of-charge`` field.
        If that doesn't work, we try the (old-style) asset attribute.
        Finally, we default the starting soc to 0 (only if there are soc limits, though, as some assets don't use
        the concept of a state of charge, and without soc targets and limits the starting soc doesn't matter).
        """
        if flex_model is None:
            flex_model = self.flex_model
        if sensor is None:
            sensor = self.sensor

        if not self.has_soc_at_start_in(flex_model) and "state-of-charge" in flex_model:
            flex_model["soc-at-start"] = (
                str(self._resolve_soc_at_start_from_state_of_charge(flex_model, sensor))
                + "MWh"
            )

        if not self.has_soc_at_start_in(flex_model) and sensor is not None:
            # TODO: remove this check when moving to v1.0 (requiring to also remove attributes from test data assets)
            if (
                self.start == sensor.get_attribute("soc_datetime")
                and sensor.get_attribute("soc_in_mwh") is not None
            ):
                flex_model["soc-at-start"] = sensor.get_attribute("soc_in_mwh")
        if not self.has_soc_at_start_in(flex_model) and (
            "soc-min" in flex_model or "soc-max" in flex_model
        ):
            flex_model["soc-at-start"] = 0

        return flex_model

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

    def _get_device_power_capacity(
        self,
        flex_model: list[dict],
        assets: list[Asset],
        query_window: tuple[datetime, datetime],
        resolution: timedelta,
        beliefs_before: datetime | None,
    ) -> list[Sensor | SensorReference | list[dict] | ur.Quantity | pd.Series]:
        """The device power capacity for each device must be known for the optimization problem to stay bounded.

        We search for the power capacity in the following order:
        1. Look for the power_capacity_in_mw field in the deserialized flex-model.
        2. Look for the power-capacity flex-model field of the asset.
        3. Look for the greatest device consumption-capacity or production-capacity.
        4. Look for the site-power-capacity attribute of the asset.
        """
        power_capacities = []
        for flex_model_d, asset in zip(flex_model, assets):

            # 1 and 2
            power_capacity_in_mw = flex_model_d.get(
                "power_capacity_in_mw",
                asset.flex_model.get("power-capacity"),
            )
            if power_capacity_in_mw is not None:
                power_capacities.append(
                    self._ensure_variable_quantity(power_capacity_in_mw, "MW")
                )
                continue

            # 3
            fallback_capacity = self._get_largest_device_capacity(
                flex_model_d=flex_model_d,
                query_window=query_window,
                resolution=resolution,
                beliefs_before=beliefs_before,
            )
            if fallback_capacity is not None:
                current_app.logger.warning(
                    f"Missing 'power-capacity' on asset {asset.id}. "
                    "Using the largest configured directional capacity instead."
                )
                power_capacities.append(fallback_capacity)
                continue

            # 4
            site_power_capacity = asset.get_attribute("site-power-capacity")
            if site_power_capacity is not None:
                current_app.logger.warning(
                    f"Missing 'power-capacity' on asset {asset.id}. Using site-power-capacity instead."
                )
                if isinstance(site_power_capacity, dict):
                    site_power_capacity = site_power_capacity.get("sensor", None)
                    if site_power_capacity is None:
                        raise ValueError(
                            f"site-power-capacity attribute on asset {asset.id} is a dict, but has no sensor key."
                        )

                power_capacities.append(
                    self._ensure_variable_quantity(site_power_capacity, "MW")
                )
                continue

            raise ValueError(
                f"Power capacity on asset {asset.id} is not defined in the flex-model."
            )
        return power_capacities

    @staticmethod
    def _default_missing_directional_capacity_to_zero(flex_model_d: dict) -> None:
        """Given a missing capacity opposite a non-zero directional capacity, default the missing capacity to zero."""
        consumption_capacity = flex_model_d.get("consumption_capacity")
        production_capacity = flex_model_d.get("production_capacity")
        has_consumption_capacity = consumption_capacity is not None
        has_production_capacity = production_capacity is not None

        if (
            has_consumption_capacity
            and not has_production_capacity
            and MetaStorageScheduler._is_non_zero_capacity(consumption_capacity)
        ):
            flex_model_d["production_capacity"] = ur.Quantity("0 MW")
        elif (
            has_production_capacity
            and not has_consumption_capacity
            and MetaStorageScheduler._is_non_zero_capacity(production_capacity)
        ):
            flex_model_d["consumption_capacity"] = ur.Quantity("0 MW")

    @staticmethod
    def _is_non_zero_capacity(
        capacity: str | int | float | ur.Quantity | Sensor | SensorReference | list,
    ) -> bool:
        """Return whether a configured capacity should imply zero capacity in the opposite direction."""
        if isinstance(capacity, (Sensor, SensorReference)):
            return True
        if isinstance(capacity, list):
            return any(
                MetaStorageScheduler._is_non_zero_capacity(event["value"])
                for event in capacity
            )
        if isinstance(capacity, str):
            capacity = ur.Quantity(capacity)
        if isinstance(capacity, ur.Quantity):
            return bool(np.any(capacity.magnitude != 0))
        return capacity != 0

    def _get_largest_device_capacity(
        self,
        flex_model_d: dict,
        query_window: tuple[datetime, datetime],
        resolution: timedelta,
        beliefs_before: datetime | None,
    ) -> Sensor | SensorReference | list[dict] | ur.Quantity | pd.Series | None:
        """Return the largest configured directional capacity, if any."""
        capacity_fields = ("consumption_capacity", "production_capacity")
        configured_capacity_fields = [
            field for field in capacity_fields if flex_model_d.get(field) is not None
        ]
        if not configured_capacity_fields:
            return None
        capacities = [
            self._ensure_variable_quantity(flex_model_d[field], "MW")
            for field in configured_capacity_fields
        ]

        capacity_series = [
            get_continuous_series_sensor_or_quantity(
                variable_quantity=capacity,
                unit="MW",
                query_window=query_window,
                resolution=resolution,
                beliefs_before=beliefs_before,
                min_value=0,
                # Normally, we'd resolve overlapping time series segments for capacities with "min", but here our goal is to find the maximum capacity.
                resolve_overlaps="max",
            )
            for capacity in capacities
        ]
        largest_capacity = pd.concat(capacity_series, axis=1).max(axis=1)
        if largest_capacity.isna().all():
            return None
        if (
            len(configured_capacity_fields) == 1
            and largest_capacity.fillna(0).eq(0).all()
        ):
            return None
        return largest_capacity

    def _ensure_variable_quantity(
        self, value: str | int | float | ur.Quantity | pd.Series, unit: str
    ) -> Sensor | SensorReference | list[dict] | ur.Quantity | pd.Series:
        if isinstance(value, str):
            q = ur.Quantity(value).to(unit)
        elif isinstance(value, (float, int)):
            q = ur.Quantity(f"{value} {unit}")
        elif isinstance(value, (Sensor, SensorReference, list, ur.Quantity, pd.Series)):
            q = value
        else:
            raise TypeError(
                f"Unsupported type '{type(value)}' to describe Quantity. Value: {value}"
            )
        return q


class StorageScheduler(MetaStorageScheduler):
    __version__ = "8"
    __author__ = "Seita"

    @staticmethod
    def _build_soc_schedule(  # noqa: C901
        flex_model: list[dict],
        ems_schedule: list[pd.Series],
        soc_at_start: list[float],
        device_constraints: list,
        resolution: timedelta,
        stock_groups: dict[int, list[int]],
    ) -> tuple[dict, dict]:
        """Build the state-of-charge schedule for each stock group.

        Supports both:
        - original logic: one device per stock group
        - local/shared-stock logic: multiple devices contribute to one shared stock

        For shared stock groups, each device contribution is integrated separately with
        its own efficiencies and stock delta, then summed on top of the shared initial stock.

        Also computes the MWh SoC for devices that have ``soc-minima`` or ``soc-maxima`` constraints
        (even without a state-of-charge sensor) so that unresolved targets can be checked later.
        For a shared stock group, every device in the group is tracked against the group's
        combined MWh SoC series, since they share the same physical stock.

        Converts the integrated stock schedule from MWh to the state-of-charge sensor unit.
        For '%' sensors, the soc-max flex-model field is used as capacity.
        If soc-max is missing or zero for a '%' sensor, the schedule is skipped with a warning.

        Note: soc-max is a QuantityField (not a VariableQuantityField), so it is always a float
        after deserialization and cannot be a sensor reference.
        The isinstance guard below is therefore a defensive check for forward-compatibility.

        :returns: Tuple of (soc_schedule keyed by SoC sensor in sensor unit,
                            soc_schedule_mwh keyed by device index in MWh).
        """
        soc_schedule = {}
        soc_schedule_mwh = {}

        for stock_id, devices in stock_groups.items():
            if not devices:
                continue

            d0 = devices[0]
            flex_model_d0 = flex_model[d0]

            state_of_charge_sensor = flex_model_d0.get("state_of_charge")
            if isinstance(state_of_charge_sensor, SensorReference):
                state_of_charge_sensor = state_of_charge_sensor.sensor
            has_soc_sensor = isinstance(state_of_charge_sensor, Sensor)
            has_soc_minima_maxima = any(
                flex_model[d].get("soc_minima") is not None
                or flex_model[d].get("soc_maxima") is not None
                for d in devices
            )
            # Skip stock groups that neither have a SoC sensor nor soc-minima/soc-maxima constraints
            if not has_soc_sensor and not has_soc_minima_maxima:
                continue
            # Skip stock groups without a known initial SoC (required for integration)
            if soc_at_start[d0] is None:
                continue

            # Build the SoC series (in MWh) for this stock group
            if len(devices) > 1:
                soc_contributions = []
                reference_index = None

                for d in devices:
                    contribution = integrate_time_series(
                        series=ems_schedule[d],
                        initial_stock=0,
                        stock_delta=device_constraints[d]["stock delta"]
                        * resolution
                        / timedelta(hours=1),
                        up_efficiency=device_constraints[d]["derivative up efficiency"],
                        down_efficiency=device_constraints[d][
                            "derivative down efficiency"
                        ],
                        storage_efficiency=device_constraints[d]["efficiency"]
                        .astype(float)
                        .fillna(1),
                    )
                    soc_contributions.append(contribution)

                    if reference_index is None:
                        reference_index = contribution.index

                initial_stock = soc_at_start[d0]
                soc_mwh = pd.Series(
                    [
                        initial_stock
                        + sum(contrib.iloc[i] for contrib in soc_contributions)
                        for i in range(len(soc_contributions[0]))
                    ],
                    index=reference_index,
                )
            else:
                soc_mwh = integrate_time_series(
                    series=ems_schedule[d0],
                    initial_stock=soc_at_start[d0],
                    stock_delta=device_constraints[d0]["stock delta"]
                    * resolution
                    / timedelta(hours=1),
                    up_efficiency=device_constraints[d0]["derivative up efficiency"],
                    down_efficiency=device_constraints[d0][
                        "derivative down efficiency"
                    ],
                    storage_efficiency=device_constraints[d0]["efficiency"]
                    .astype(float)
                    .fillna(1),
                )

            # Record the MWh SoC for each device in this stock group, keyed by device
            # index, so unresolved soc-minima/soc-maxima targets can be checked later.
            for d in devices:
                if soc_at_start[d] is not None:
                    soc_schedule_mwh[d] = soc_mwh

            # Convert to the shared SoC sensor's unit, if this group has one
            if has_soc_sensor:
                soc_unit = state_of_charge_sensor.unit
                capacity = None
                if soc_unit == "%":
                    soc_max = flex_model_d0.get("soc_max")
                    if isinstance(soc_max, (Sensor, SensorReference)):
                        raise ValueError(
                            f"Cannot convert state-of-charge schedule to '%' unit for sensor "
                            f"{state_of_charge_sensor.id}: soc-max as a sensor reference is "
                            "not supported for '%' unit conversion."
                        )
                    if not soc_max:
                        raise ValueError(
                            f"Cannot convert state-of-charge schedule to '%' unit for sensor "
                            f"{state_of_charge_sensor.id}: soc-max is missing or zero."
                        )
                    capacity = (
                        f"{soc_max} MWh"  # all flex model fields are in MWh by now
                    )

                soc_schedule[state_of_charge_sensor] = convert_units(
                    soc_mwh,
                    from_unit="MWh",
                    to_unit=soc_unit,
                    capacity=capacity,
                )

        return soc_schedule, soc_schedule_mwh

    def _compute_unresolved_targets(
        self,
        flex_model: list[dict],
        soc_schedule_mwh: dict,
        start: datetime,
        end: datetime,
        resolution: timedelta,
        most_relevant_only: bool = False,
    ) -> tuple[list, list]:
        """Compute unmet and met SoC minima/maxima targets per device.

        For each device that has ``soc-minima`` or ``soc-maxima`` constraints in the flex model,
        compares the computed MWh SoC schedule against those constraints.
        Devices without a ``state_of_charge`` Sensor are included
        as long as a device key can be determined from the power sensor.

        The result includes asset ID for each constraint.
        Devices for which an asset ID cannot be determined are skipped.

        Constraints are evaluated over the window ``(start + resolution, end)``
        (i.e. the first scheduled slot through the end of the schedule).
        The ``start`` slot itself is the initial condition (``soc_at_start``),
        not a scheduled value, so it is excluded.

        Note: ``soc-targets`` are modelled as hard constraints and are not checked here,
        as by definition the scheduler will not allow any deviation from them.

        :param flex_model:        The deserialized flex model (list of per-device dicts).
        :param soc_schedule_mwh:  MWh SoC schedule keyed by device index ``d``.
        :param start:             Start of the schedule.
        :param end:               End of the schedule.
        :param resolution:        Schedule resolution.
        :param most_relevant_only: If False (the default), report every violated/met slot.
                                    If True, report only the single most relevant slot
                                    (the first violation, or the tightest margin).
                                    Either way, the result holds a list.
        :returns: A tuple ``(unresolved, resolved)``.

                  ``unresolved`` is a list of dicts, each with ``"asset"`` field and constraint info.
                  Each constraint entry is a list of dicts
                  ``{"datetime": <ISO 8601 UTC string>, "violation": "<value> kWh"}``
                  (one per violated slot, or just the first if ``most_relevant_only`` is True),
                  where ``violation`` is always positive.

                  ``resolved`` is also a list of dicts with ``"asset"`` field and constraint info.
                  Each constraint entry is a list of dicts
                  ``{"datetime": <ISO 8601 UTC string>, "margin": "<value> kWh"}``
                  (one per met slot, or just the slot with the tightest/smallest positive
                  margin if ``most_relevant_only`` is True).
        """
        # Use the configured rounding precision, or the scheduler's default of 6.
        precision = self.round_to_decimals if self.round_to_decimals is not None else 6

        unresolved: list = []
        resolved: list = []

        for d, flex_model_d in enumerate(flex_model):
            soc_mwh = soc_schedule_mwh.get(d)
            if soc_mwh is None:
                continue

            # Determine device key: prefer asset ID, fall back to power sensor ID.
            # Devices without a state-of-charge sensor are included as long as a
            # key can be derived from the power sensor's generic asset (or the
            # power sensor itself).
            # In single-sensor mode the flex_model entry has no "sensor" key;
            # fall back to self.sensor (set when the scheduler was given a Sensor).
            power_sensor = flex_model_d.get("sensor") or self.sensor
            if (
                power_sensor is not None
                and hasattr(power_sensor, "generic_asset")
                and power_sensor.generic_asset is not None
            ):
                asset_id = power_sensor.generic_asset.id
            else:
                continue

            device_violations: dict = {}
            device_resolved: dict = {}

            # Check soc_minima (first time slot where scheduled SoC < minima)
            soc_minima_d = flex_model_d.get("soc_minima")
            if soc_minima_d is not None:
                soc_minima_series = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_minima_d,
                    unit="MWh",
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=self.belief_time,
                    as_instantaneous_events=True,
                    resolve_overlaps="max",
                )
                defined_minima = soc_minima_series.dropna()
                if len(defined_minima) > 0:
                    aligned_soc = soc_mwh.reindex(defined_minima.index)
                    shortages = defined_minima - aligned_soc
                    violations = shortages[shortages > 0]
                    if not violations.empty:
                        violation_times = (
                            [violations.index[0]]
                            if most_relevant_only
                            else violations.index
                        )
                        device_violations["soc-minima"] = [
                            {
                                "datetime": t.tz_convert("UTC").isoformat(),
                                "violation": f"{round(float(violations[t]) * 1000, precision)} kWh",
                            }
                            for t in violation_times
                        ]
                    else:
                        # All minima met — margins are the headroom above the minimum.
                        # violations.empty guarantees shortages <= 0, so margins (soc - minima) >= 0.
                        margins = aligned_soc - defined_minima
                        margin_times = (
                            [margins.idxmin()] if most_relevant_only else margins.index
                        )
                        device_resolved["soc-minima"] = [
                            {
                                "datetime": t.tz_convert("UTC").isoformat(),
                                "margin": f"{round(float(margins[t]) * 1000, precision)} kWh",
                            }
                            for t in margin_times
                        ]

            # Check soc_maxima (first time slot where scheduled SoC > maxima)
            soc_maxima_d = flex_model_d.get("soc_maxima")
            if soc_maxima_d is not None:
                soc_maxima_series = get_continuous_series_sensor_or_quantity(
                    variable_quantity=soc_maxima_d,
                    unit="MWh",
                    query_window=(start + resolution, end + resolution),
                    resolution=resolution,
                    beliefs_before=self.belief_time,
                    as_instantaneous_events=True,
                    resolve_overlaps="min",
                )
                defined_maxima = soc_maxima_series.dropna()
                if len(defined_maxima) > 0:
                    aligned_soc = soc_mwh.reindex(defined_maxima.index)
                    excesses = aligned_soc - defined_maxima
                    violations = excesses[excesses > 0]
                    if not violations.empty:
                        violation_times = (
                            [violations.index[0]]
                            if most_relevant_only
                            else violations.index
                        )
                        device_violations["soc-maxima"] = [
                            {
                                "datetime": t.tz_convert("UTC").isoformat(),
                                "violation": f"{round(float(violations[t]) * 1000, precision)} kWh",
                            }
                            for t in violation_times
                        ]
                    else:
                        # All maxima met — margins are the headroom below the maximum.
                        # violations.empty guarantees excesses <= 0, so margins (maxima - soc) >= 0.
                        margins = defined_maxima - aligned_soc
                        margin_times = (
                            [margins.idxmin()] if most_relevant_only else margins.index
                        )
                        device_resolved["soc-maxima"] = [
                            {
                                "datetime": t.tz_convert("UTC").isoformat(),
                                "margin": f"{round(float(margins[t]) * 1000, precision)} kWh",
                            }
                            for t in margin_times
                        ]

            if device_violations:
                violation_entry = {"asset": asset_id}
                violation_entry.update(device_violations)
                unresolved.append(violation_entry)
            if device_resolved:
                resolved_entry = {"asset": asset_id}
                resolved_entry.update(device_resolved)
                resolved.append(resolved_entry)

        return unresolved, resolved

    @staticmethod
    def _build_consumption_production_schedules(
        flex_model: list[dict],
        ems_schedule: pd.DataFrame,
    ) -> dict:
        """Build consumption and/or production power schedules for devices that define output sensors.

        Each device's flex model may define a ``consumption`` sensor, a ``production`` sensor, or both.
        The schedule stored on each sensor depends on which sensors are defined:

        - **Only** ``consumption`` **sensor defined**: the full power schedule is written to that
          sensor using the scheduler's native sign convention (consumption positive, production
          negative). ``make_schedule`` applies no further sign change because the sensor already
          has ``consumption_is_positive=True``.
        - **Only** ``production`` **sensor defined**: the full power schedule is written to that
          sensor in the scheduler's native sign convention (consumption positive, production
          negative). ``make_schedule`` inverts the sign based on the sensor's
          ``consumption_is_positive=False`` attribute so that production is stored as positive values.
        - **Both** ``consumption`` **and** ``production`` **sensors defined**: only the non-negative
          part of the schedule (charging / consuming) is written to the consumption sensor, and only
          the non-positive part (discharging / producing, still as negative values) is written to
          the production sensor. ``make_schedule`` inverts the sign for the production sensor.

        The ``consumption_is_positive`` attribute is set on each output sensor when the scheduling
        job is created (see ``create_scheduling_job``), not here. This method only clips the
        series; sign handling is left entirely to ``make_schedule``.

        Unit conversion from MW to each sensor's unit is applied.

        :param flex_model:    List of per-device flex models (after deserialization).
        :param ems_schedule:  DataFrame of per-device power schedules in MW (consumption positive).
        :returns:             Dict mapping each output sensor to its power schedule.
        """
        schedules: dict = {}
        for d, flex_model_d in enumerate(flex_model):
            consumption_field = flex_model_d.get("consumption")
            production_field = flex_model_d.get("production")
            consumption_sensor = (
                consumption_field["sensor"]
                if isinstance(consumption_field, dict) and "sensor" in consumption_field
                else None
            )
            production_sensor = (
                production_field["sensor"]
                if isinstance(production_field, dict) and "sensor" in production_field
                else None
            )
            if consumption_sensor is None and production_sensor is None:
                continue
            power_series = ems_schedule[d]  # in MW; consumption is positive
            if consumption_sensor is not None and production_sensor is None:
                # Full power profile on the consumption sensor (consumption positive, production negative).
                schedules[consumption_sensor] = convert_units(
                    power_series,
                    "MW",
                    consumption_sensor.unit,
                    event_resolution=consumption_sensor.event_resolution,
                )
            elif production_sensor is not None and consumption_sensor is None:
                # Full power profile on the production sensor in native scheduler convention.
                # make_schedule inverts the sign via consumption_is_positive=False on the sensor.
                schedules[production_sensor] = convert_units(
                    power_series,
                    "MW",
                    production_sensor.unit,
                    event_resolution=production_sensor.event_resolution,
                )
            else:
                # Both sensors defined: clip to non-negative (consumption) and non-positive (production) parts.
                # make_schedule inverts the sign for the production sensor via consumption_is_positive=False.
                schedules[consumption_sensor] = convert_units(
                    power_series.clip(lower=0),
                    "MW",
                    consumption_sensor.unit,
                    event_resolution=consumption_sensor.event_resolution,
                )
                schedules[production_sensor] = convert_units(
                    power_series.clip(upper=0),
                    "MW",
                    production_sensor.unit,
                    event_resolution=production_sensor.event_resolution,
                )
        return schedules

    def _reconstruct_commodity_to_devices(self) -> dict[str, list[int]]:
        """Return the mapping of commodity -> device indices, as enumerated by the device inventory.

        Device enumeration order (the inventory's canonical order, also used by `_prepare()`):
            1. flexible devices (from the flex-model), in order,
            2. top-level (electricity) inflexible-device-sensors, in order,
            3. each commodity context's own inflexible-device-sensors, in the order the
               commodity contexts are given.

        The returned device indices line up with entries of `ems_schedule` /
        `device_constraints`.
        """
        inventory = self.device_inventory
        if inventory is None:
            # Fallback (e.g. bare schedulers in tests): classify the stored device
            # models, or failing that, the flex-model itself.
            flex_model = getattr(self, "_device_models", None)
            if flex_model is None:
                flex_model = (
                    self.flex_model.copy()
                    if isinstance(self.flex_model, dict)
                    else [fm for fm in self.flex_model if fm.get("sensor") is not None]
                )
            inventory = DeviceInventory.from_flex_config(
                flex_model, self.flex_context, sensor=getattr(self, "sensor", None)
            )
        return inventory.commodity_to_devices

    def _electricity_device_indices(self) -> list[int]:
        """Return the device indices (flexible and inflexible) belonging to the electricity commodity."""
        return self._reconstruct_commodity_to_devices().get("electricity", [])

    def _compute_commodity_aggregate_schedules(
        self,
        storage_schedule: dict,
        ems_schedule: pd.DataFrame,
    ) -> None:
        """Compute per-commodity aggregate power flows for aggregate-consumption and aggregate-production sensors.

        This method populates the storage_schedule dict with aggregate schedules for each commodity
        that defines aggregate-consumption and/or aggregate-production sensors in its commodity context.

        The sign convention and split logic follows the same pattern as _build_consumption_production_schedules:
        - Only aggregate-consumption defined: full aggregate schedule (consumption +, production -)
        - Only aggregate-production defined: full aggregate schedule (consumption +, production -)
          (sign will be flipped by make_schedule based on consumption_is_positive=False)
        - Both defined: consumption sensor gets non-negative part, production sensor gets non-positive part
          (sign will be flipped for production by make_schedule)

        For backwards compatibility, when no commodity_contexts are defined, all devices are treated
        as electricity devices and use the top-level flex-context fields.

        :param storage_schedule: Dict to populate with aggregate schedules (will be modified in-place)
        :param ems_schedule:     DataFrame of per-device power schedules in MW (consumption positive)
        """
        commodity_to_devices = self._reconstruct_commodity_to_devices()

        # Get commodity contexts (handles backwards compatibility)
        commodity_contexts = self._get_commodity_contexts()

        # Process each commodity
        for commodity, devices in commodity_to_devices.items():
            commodity_context = commodity_contexts.get(commodity, {})

            # Get aggregate sensors for this commodity
            aggregate_consumption_field = commodity_context.get("aggregate_consumption")
            aggregate_production_field = commodity_context.get("aggregate_production")

            # Extract sensor objects
            aggregate_consumption_sensor = (
                aggregate_consumption_field.get("sensor")
                if isinstance(aggregate_consumption_field, dict)
                and "sensor" in aggregate_consumption_field
                else None
            )
            aggregate_production_sensor = (
                aggregate_production_field.get("sensor")
                if isinstance(aggregate_production_field, dict)
                and "sensor" in aggregate_production_field
                else None
            )

            # Skip if no aggregate sensors defined for this commodity
            if (
                aggregate_consumption_sensor is None
                and aggregate_production_sensor is None
            ):
                continue

            # Sum the schedules for all devices in this commodity
            # ems_schedule is a list of Series, one per device
            device_indices = [d for d in devices if d < len(ems_schedule)]

            # If no devices contribute to this commodity's aggregate, skip it
            # (e.g., heat commodity with no heat devices)
            if not device_indices:
                continue

            commodity_aggregate = sum(ems_schedule[d] for d in device_indices)

            # Apply split logic based on which sensors are defined
            if (
                aggregate_consumption_sensor is not None
                and aggregate_production_sensor is None
            ):
                # Only consumption sensor: full aggregate schedule
                # (consumption positive, production negative)
                storage_schedule[aggregate_consumption_sensor] = commodity_aggregate

            elif (
                aggregate_production_sensor is not None
                and aggregate_consumption_sensor is None
            ):
                # Only production sensor: full aggregate schedule in native convention
                # make_schedule will flip the sign via consumption_is_positive=False
                storage_schedule[aggregate_production_sensor] = commodity_aggregate

            else:
                # Both sensors defined: split into consumption (>=0) and production (<=0) parts
                # make_schedule will flip the sign for production sensor via consumption_is_positive=False
                storage_schedule[aggregate_consumption_sensor] = (
                    commodity_aggregate.clip(lower=0)
                )
                storage_schedule[aggregate_production_sensor] = (
                    commodity_aggregate.clip(upper=0)
                )

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

        initial_stock = [0] * len(soc_at_start)

        for stock_id, devices in self.stock_groups.items():
            d0 = devices[0]
            s = soc_at_start[d0]

            value = s * (timedelta(hours=1) / resolution) if s is not None else 0

            for d in devices:
                initial_stock[d] = value

        ems_schedule, expected_costs, scheduler_results, model = device_scheduler(
            device_constraints=device_constraints,
            ems_constraints=ems_constraints,
            ems_constraint_groups=self.ems_constraint_groups,
            commitments=commitments,
            initial_stock=initial_stock,
            stock_groups=self.stock_groups,
        )
        if "infeasible" in (tc := scheduler_results.solver.termination_condition):
            raise InfeasibleProblemException(tc)

        # Obtain the storage schedule from all device schedules within the EMS
        storage_schedule = dict()
        # Accumulate schedules when multiple devices share the same sensor.
        for d, sensor in enumerate(sensors):
            if sensor is not None and sensor not in storage_schedule:
                storage_schedule[sensor] = ems_schedule[d]
            elif sensor is not None and sensor in storage_schedule:
                storage_schedule[sensor] += ems_schedule[d]

        # Obtain the aggregate power schedule, too, if the flex-context states the associated sensor. Fill with the sum of schedules made here.
        # Restricted to electricity devices (flexible and inflexible), per decision.
        aggregate_power_sensor = self.flex_context.get("aggregate_power", None)
        if isinstance(aggregate_power_sensor, Sensor):
            electricity_devices = self._electricity_device_indices()
            storage_schedule[aggregate_power_sensor] = pd.concat(
                [ems_schedule[d] for d in electricity_devices if d < len(ems_schedule)],
                axis=1,
            ).sum(axis=1)
        # Compute per-commodity aggregate power flows for aggregate-consumption and aggregate-production sensors
        self._compute_commodity_aggregate_schedules(storage_schedule, ems_schedule)

        # Convert each device schedule to the unit of the device's power sensor
        storage_schedule = {
            sensor: convert_units(
                storage_schedule[sensor],
                "MW",
                sensor.unit,
                event_resolution=sensor.event_resolution,
            )
            for sensor in storage_schedule.keys()
            if sensor is not None
        }

        # Use the filtered device_models (stored during _prepare) not self.flex_model
        # because stock_groups was rebuilt with device indices, not original indices
        flex_model_for_soc = getattr(self, "_device_models", None)
        if flex_model_for_soc is None:
            # Fallback: reconstruct if not available (shouldn't happen in normal flow)
            flex_model_for_soc = (
                self.flex_model.copy()
                if isinstance(self.flex_model, dict)
                else [fm for fm in self.flex_model if fm.get("sensor") is not None]
            )

        if not isinstance(flex_model_for_soc, list):
            flex_model_for_soc = [flex_model_for_soc]

        soc_schedule, soc_schedule_mwh = self._build_soc_schedule(
            flex_model=flex_model_for_soc,
            ems_schedule=ems_schedule,
            soc_at_start=soc_at_start,
            device_constraints=device_constraints,
            stock_groups=self.stock_groups,
            resolution=resolution,
        )

        consumption_production_schedule = self._build_consumption_production_schedules(
            flex_model_for_soc, ems_schedule
        )

        # Resample each device schedule to the resolution of the device's power sensor
        if self.resolution is None:
            storage_schedule = {
                sensor: storage_schedule[sensor]
                .resample(sensor.event_resolution)
                .mean()
                for sensor in storage_schedule.keys()
                if sensor is not None
            }
            consumption_production_schedule = {
                sensor: consumption_production_schedule[sensor]
                .resample(sensor.event_resolution)
                .mean()
                for sensor in consumption_production_schedule.keys()
            }

        # Round schedule
        if self.round_to_decimals:
            storage_schedule = {
                sensor: storage_schedule[sensor].round(self.round_to_decimals)
                for sensor in storage_schedule.keys()
                if sensor is not None
            }
            soc_schedule = {
                sensor: soc_schedule[sensor].round(self.round_to_decimals)
                for sensor in soc_schedule.keys()
            }
            consumption_production_schedule = {
                sensor: consumption_production_schedule[sensor].round(
                    self.round_to_decimals
                )
                for sensor in consumption_production_schedule.keys()
            }
            # Round the MWh SoC schedule to the same precision so that violation
            # detection does not flag floating-point epsilon differences.
            soc_schedule_mwh = {
                d: series.round(self.round_to_decimals)
                for d, series in soc_schedule_mwh.items()
            }

        if self.return_multiple:
            unresolved, resolved = self._compute_unresolved_targets(
                flex_model_for_soc, soc_schedule_mwh, start, end, resolution
            )
            storage_schedules = [
                {
                    "name": "storage_schedule",
                    "sensor": sensor,
                    "data": storage_schedule[sensor],
                    "unit": sensor.unit,
                }
                for sensor in storage_schedule.keys()
                if sensor is not None
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
            # Determine which sensors are consumption vs. production output sensors
            consumption_output_sensors = {
                flex_model_d["consumption"]["sensor"]
                for flex_model_d in flex_model_for_soc
                if isinstance(flex_model_d.get("consumption"), dict)
                and "sensor" in flex_model_d["consumption"]
            }
            consumption_production_schedules = [
                {
                    "name": (
                        "consumption_schedule"
                        if sensor in consumption_output_sensors
                        else "production_schedule"
                    ),
                    "data": data,
                    "sensor": sensor,
                    "unit": sensor.unit,
                }
                for sensor, data in consumption_production_schedule.items()
            ]
            scheduling_result = [
                {
                    "name": SCHEDULING_RESULT_KEY,
                    "data": SchedulingJobResult(
                        unresolved=unresolved,
                        resolved=resolved,
                    ),
                }
            ]
            return (
                storage_schedules
                + commitment_costs
                + soc_schedules
                + consumption_production_schedules
                + scheduling_result
            )
        else:
            return storage_schedule[sensors[0]]


def create_constraint_violations_message(constraint_violations: list) -> str:
    """Create a human-readable message with the constraint_violations.

    :param constraint_violations:   List with the constraint violations.
    :returns:                       Human-readable message.
    """
    message = ""

    for c in constraint_violations:
        message += f"t={c['dt']} | {c['violation']}\n"

    if len(message) > 1:
        message = message[:-1]

    return message


def build_device_soc_values(
    soc_values: ur.Quantity | list[dict[str, datetime | float]] | pd.Series | None,
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
    elif isinstance(soc_values, ur.Quantity):
        device_values = initialize_series(
            soc_values.magnitude,
            start=start_of_schedule,
            end=end_of_schedule,
            resolution=resolution,
            inclusive="right",  # note that target values are indexed by their due date (i.e. inclusive="right")
        )
    elif soc_values is None:
        device_values = initialize_series(
            np.nan,
            start=start_of_schedule,
            end=end_of_schedule,
            resolution=resolution,
            inclusive="right",  # note that target values are indexed by their due date (i.e. inclusive="right")
        )
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
            if isinstance(soc, ur.Quantity):
                soc = soc.magnitude
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

            if (
                soc_constraint_start == soc_constraint_end
                and soc_constraint_start not in device_values.index
            ):
                # Point-like events between scheduling ticks match no index entry.
                # This can happen when off-tick projection is disabled through the
                # sensor's floor_datetimes_to_resolution attribute.
                current_app.logger.warning(
                    f"Disregarding off-tick SoC constraint at {soc_constraint_start} "
                    f"(value: {soc}): it does not fall on the scheduling ticks and "
                    f"off-tick projection is disabled for this sensor."
                )
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
    soc_max: float | None,
    soc_min: float | None,
) -> pd.DataFrame:
    """Collect all constraints for a given storage device in a DataFrame that the device_scheduler can interpret.

    :param start:                       Start of the schedule.
    :param end:                         End of the schedule.
    :param resolution:                  Timedelta used to resample the constraints to the resolution of the schedule.
    :param soc_at_start:                State of charge at the start time.
    :param soc_targets:                 Exact targets for the state of charge at each time.
    :param soc_maxima:                  Maximum state of charge at each time.
    :param soc_minima:                  Minimum state of charge at each time.
    :param soc_max:                     Maximum state of charge at all times, if configured.
    :param soc_min:                     Minimum state of charge at all times, if configured.
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

    soc_min_change = (
        (soc_min - soc_at_start) * timedelta(hours=1) / resolution
        if soc_min is not None
        else None
    )
    soc_max_change = (
        (soc_max - soc_at_start) * timedelta(hours=1) / resolution
        if soc_max is not None
        else None
    )

    if soc_minima is not None:
        storage_device_constraints["min"] = build_device_soc_values(
            soc_minima,
            soc_at_start,
            start,
            end,
            resolution,
        )

    storage_device_constraints["min"] = storage_device_constraints["min"].astype(float)
    if soc_min_change is not None:
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

    storage_device_constraints["max"] = storage_device_constraints["max"].astype(float)
    if soc_max_change is not None:
        storage_device_constraints["max"] = storage_device_constraints["max"].fillna(
            soc_max_change
        )

    # Limit max and min to the constant bounds that are configured.
    storage_device_constraints["min"] = (
        storage_device_constraints["min"].clip(
            lower=soc_min_change, upper=soc_max_change
        )
        if soc_min_change is not None
        else storage_device_constraints["min"].clip(upper=soc_max_change)
    )
    storage_device_constraints["max"] = storage_device_constraints["max"].clip(
        lower=soc_min_change, upper=soc_max_change
    )

    return storage_device_constraints


def validate_storage_constraints(
    constraints: pd.DataFrame,
    soc_at_start: float,
    soc_min: float | None,
    soc_max: float | None,
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
    :param soc_min:             Minimum state of charge at all times, if configured.
    :param soc_max:             Maximum state of charge at all times, if configured.
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
    if soc_min is not None:
        soc_min = (soc_min - soc_at_start) * timedelta(hours=1) / resolution
        _constraints["soc_min(t)"] = soc_min
        constraint_violations += validate_constraint(
            _constraints, "soc_min(t)", "<=", "min(t)"
        )
    else:
        soc_min = np.nan

    # 2) max <= soc_max
    if soc_max is not None:
        soc_max = (soc_max - soc_at_start) * timedelta(hours=1) / resolution
        _constraints["soc_max(t)"] = soc_max
        constraint_violations += validate_constraint(
            _constraints, "max(t)", "<=", "soc_max(t)"
        )
    else:
        soc_max = np.nan

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

    :returns: regex expression
    """

    regex = r"(^|\s|$|\b|\+|\-|\*|\/\|\\)"

    return regex + re.escape(word) + regex


def sanitize_expression(expression: str, columns: list) -> tuple[str, list]:
    """Wrap column in commas to accept arbitrary column names (e.g. with spaces).

    :param expression:  Expression to sanitize.
    :param columns:     List with the name of the columns of the input data for the expression.
    :returns:           Sanitized expression and columns (variables) used in the expression.
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
    :returns:                   List of constraint violations, specifying their time, constraint and violation.
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
