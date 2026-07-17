import pandas as pd
import pytest
import numpy as np

from flexmeasures.data.services.utils import get_or_create_model
from flexmeasures.data.models.planning import (
    Commitment,
    StockCommitment,
    FlowCommitment,
)
from flexmeasures.data.models.planning.utils import (
    initialize_index,
)
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.planning.linear_optimization import device_scheduler
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.utils import save_to_db


def test_multi_feed_device_scheduler_shared_buffer():
    # ---- time setup
    start = pd.Timestamp("2026-01-01T00:00+01")
    end = pd.Timestamp("2026-01-02T00:00+01")
    resolution = pd.Timedelta("PT1H")
    index = initialize_index(start=start, end=end, resolution=resolution)

    # ---- three devices
    devices = ["gas boiler", "heat pump power", "battery power"]

    # ---- device grouping
    device_group = pd.Series(
        {
            0: "shared thermal buffer",  # gas boiler
            1: "shared thermal buffer",  # "heat pump power"
            2: "battery SoC",  # "battery power"
        }
    )
    device_commodity = pd.Series(
        {
            0: "gas",  # gas boiler
            1: "electricity",  # "heat pump power"
            2: "electricity",  # "battery power"
        }
    )
    equals = pd.Series(np.nan, index=index)
    equals[-1] = 100
    device_constraints = []
    for d, device_name in enumerate(devices):
        # 0 and 1 : derivative min 0
        # 2 : derivative min = - production capacity

        df = pd.DataFrame(
            {
                "min": 0,
                "max": 100,
                "equals": np.nan,
                "derivative min": 0 if d in (0, 1) else -20,
                "derivative max": 20,
                "derivative equals": np.nan,
                "derivative down efficiency": 0.9,
                "derivative up efficiency": 0.9,
            },
            index=index,
        )
        device_constraints.append(df)

    ems_constraints = pd.DataFrame(
        {
            "derivative min": -40,
            "derivative max": 40,
        },
        index=index,
    )

    # ---- shared buffer max = 100 (soft)
    max_soc = 100.0
    breach_price = 1_000.0
    min_soc = pd.Series(0, index=index)
    min_soc[-1] = 100

    # default commodity: electricity
    # choice: electricity or gas
    gas_price = pd.Series(300, index=index)
    electricity_price = pd.Series(600, index=index, name="event_value")
    electricity_price.iloc[12:14] = 200
    prices = {"gas": gas_price, "electricity": electricity_price}

    # Tie-breaking: prefer filling each device's storage as early as possible.
    soc_max = 100.0
    penalty = 0.001

    commitments = []

    commitments.append(
        StockCommitment(
            name="buffer min",
            index=index,
            quantity=min_soc,
            upwards_deviation_price=0,
            downwards_deviation_price=-breach_price,
            # instead of device=None, I considered to create a series for the devices that we need for this
            # specific commitment.
            device=pd.Series([[0, 1]] * len(index), index=index),
            device_group=device_group,
        )
    )
    for d, dev in enumerate(devices):
        commitments.append(
            StockCommitment(
                name="buffer max",
                index=index,
                quantity=max_soc,
                upwards_deviation_price=breach_price,
                downwards_deviation_price=0,
                device=pd.Series(d, index=index),
                device_group=device_group,
            )
        )
        commitments.append(
            FlowCommitment(
                name=device_commodity[d],
                index=index,
                quantity=0,
                upwards_deviation_price=prices[device_commodity[d]],
                downwards_deviation_price=prices[device_commodity[d]],
                device=pd.Series(d, index=index),
                device_group=device_commodity,
                commodity=device_commodity[d],
            )
        )

        commitments.append(
            StockCommitment(
                name=f"prefer a full storage {d} sooner",
                index=index,
                quantity=soc_max,
                upwards_deviation_price=0,
                downwards_deviation_price=-penalty,
                device=pd.Series(d, index=index),
                device_group=device_commodity,
                commodity=device_commodity[d],
            )
        )

    # ---- run scheduler
    planned_power, planned_costs, results, model = device_scheduler(
        device_constraints=device_constraints,
        ems_constraints=ems_constraints,
        commitments=commitments,
        initial_stock=0,
    )

    # ---- sanity: model solved optimally
    assert results.solver.termination_condition == "optimal"

    # ---- key assertion: exactly TWO commitment groups
    #   - one for "shared thermal buffer"
    #   - one for "battery SoC"
    #
    # i.e. NOT three (which would indicate per-device baselines)
    commitment_groups = set(commitments[0].device_group.values)
    commodity_commitments = {
        c.name
        for c in commitments
        if isinstance(c, FlowCommitment) and c.name in {"gas", "electricity"}
    }
    assert commodity_commitments == {"gas", "electricity"}

    # Sum per-commitment costs grouped by name so that duplicate names
    # (e.g. "electricity" for both heat pump and battery) are accumulated.
    electricity_cost = sum(
        costs
        for c, costs in zip(commitments, model.commitment_costs.values())
        if c.name == "electricity"
    )
    gas_cost = sum(
        costs
        for c, costs in zip(commitments, model.commitment_costs.values())
        if c.name == "gas"
    )
    commodity_costs = {"gas": gas_cost, "electricity": electricity_cost}

    assert set(commodity_costs.keys()) == {"gas", "electricity"}

    assert commitment_groups == {"shared thermal buffer"}

    # The shared buffer minimum (SoC ≥ 100 at the final step) must be met without any breach
    buffer_min_cost = sum(
        costs
        for c, costs in zip(commitments, model.commitment_costs.values())
        if c.name == "buffer min"
    )
    assert buffer_min_cost == 0, (
        f"Shared buffer target was breached (breach cost = {buffer_min_cost}). "
        "This may indicate that baseline costs were incorrectly duplicated."
    )

    # At hours 12–13 electricity (200) is cheaper than gas (300), so the heat pump
    # runs at full power: 2 h × 20 kW = 40 kWh flow → 40 × 0.9 = 36 kWh SoC
    # contribution to the shared buffer. The gas boiler covers the remainder:
    # (100 − 36) kWh SoC / 0.9 efficiency × 300 price.
    assert gas_cost == pytest.approx((100 - 40 * 0.9) / 0.9 * 300, rel=1e-6)

    # Expect the total electricity costs to be:
    # 2 * 20 for the heat pump
    # 2 * 20 for the battery charging
    # minus 2 * 20 * 0.9 * 0.9 for the battery discharging after roundtrip efficiency
    assert electricity_cost == pytest.approx(
        200 * (40 + 40) - 600 * (40 * 0.9 * 0.9), rel=1e-6
    )


def _run_hp_buffer_scenario(index, target_soc, shared: bool):
    """
    Helper: run the two-heat-pump scheduler with either a shared or per-device buffer
    commitment and return costs for assertions.

    Each heat pump (device 0 and 1) can supply at most
    derivative_max × hours × efficiency = 20 kW × 24 h × 0.9 = 432 kWh.

    shared=True  → one StockCommitment on the *combined* stock of devices 0+1
                   (maximum reachable: 864 kWh).
    shared=False → two separate StockCommitments, one per HP, each requiring
                   target_soc on its *own* stock (maximum per device: 432 kWh).
    """
    n = len(index)
    breach_price = 1_000.0
    energy_price = pd.Series(100, index=index)

    device_group = pd.Series(
        {
            0: "shared thermal buffer",
            1: "shared thermal buffer",
            2: "battery SoC",
        }
    )

    # ---- device constraints
    # device 0: heat pump A (charge only)
    # device 1: heat pump B (charge only)
    # device 2: battery     (charge and discharge)
    device_constraints = []
    for d in range(3):
        df = pd.DataFrame(
            {
                "min": 0,
                "max": 500,
                "equals": np.nan,
                "derivative min": 0 if d in (0, 1) else -20,
                "derivative max": 20,
                "derivative equals": np.nan,
                "derivative down efficiency": 0.9,
                "derivative up efficiency": 0.9,
            },
            index=index,
        )
        device_constraints.append(df)

    ems_constraints = pd.DataFrame(
        {"derivative min": -40, "derivative max": 40},
        index=index,
    )

    min_soc = pd.Series(0.0, index=index)
    min_soc.iloc[-1] = target_soc

    # Tie-breaking: prefer filling each device's storage as early as possible.
    soc_max = 500.0  # matches device_constraints["max"]
    penalty = 0.001

    commitments = []

    if shared:
        # One commitment covering the *combined* stock of both HPs.
        commitments.append(
            StockCommitment(
                name="buffer min",
                index=index,
                quantity=min_soc,
                upwards_deviation_price=0,
                downwards_deviation_price=-breach_price,
                device=pd.Series([[0, 1]] * n, index=index),
                device_group=device_group,
            )
        )
    else:
        # Two separate commitments, one per HP — each must reach target_soc alone.
        for d in range(2):
            commitments.append(
                StockCommitment(
                    name="buffer min",
                    index=index,
                    quantity=min_soc,
                    upwards_deviation_price=0,
                    downwards_deviation_price=-breach_price,
                    device=pd.Series(d, index=index),
                    device_group=device_group,
                )
            )

    # Individual upper bounds (soft) and energy price for all three devices.
    for d in range(3):
        commitments.append(
            StockCommitment(
                name=f"buffer max {d}",
                index=index,
                quantity=500.0,
                upwards_deviation_price=breach_price,
                downwards_deviation_price=0,
                device=pd.Series(d, index=index),
                device_group=device_group,
            )
        )
        commitments.append(
            FlowCommitment(
                name="energy",
                index=index,
                quantity=0,
                upwards_deviation_price=energy_price,
                downwards_deviation_price=energy_price,
                device=pd.Series(d, index=index),
                device_group=device_group,
            )
        )
        commitments.append(
            StockCommitment(
                name=f"prefer a full storage {d} sooner",
                index=index,
                quantity=soc_max,
                upwards_deviation_price=0,
                downwards_deviation_price=-penalty,
                device=d,
            )
        )

    planned_power, planned_costs, results, model = device_scheduler(
        device_constraints=device_constraints,
        ems_constraints=ems_constraints,
        commitments=commitments,
        initial_stock=0,
    )

    assert results.solver.termination_condition == "optimal"

    buffer_min_cost = sum(
        v
        for c, v in zip(commitments, model.commitment_costs.values())
        if c.name == "buffer min"
    )
    energy_cost = sum(
        v
        for c, v in zip(commitments, model.commitment_costs.values())
        if c.name == "energy"
    )
    return {"buffer_min_cost": buffer_min_cost, "energy_cost": energy_cost}


def test_device_group_shared_buffer():
    """
    Two heat pumps (devices 0 and 1) charge a shared thermal buffer with a target of
    800 kWh by the last time slot.

    Each HP can supply at most 20 kW × 24 h × 0.9 = 432 kWh on its own, so neither
    can reach 800 kWh individually. Together they can supply up to 864 kWh, so the
    target is feasible when the commitment tracks their *combined* stock.

    This test verifies two contrasting scenarios:

    1. Shared buffer (device_group): one StockCommitment on the combined stock of both
       HPs. The optimizer fills 800 kWh across the two devices with zero breach cost.

    2. Separate buffers (no device_group): one StockCommitment per HP, each requiring
       800 kWh on its own stock. Each HP falls short by ~368 kWh, so both commitments
       incur a breach, and the total breach cost is positive.
    """
    start = pd.Timestamp("2026-01-01T00:00+01")
    end = pd.Timestamp("2026-01-02T00:00+01")
    resolution = pd.Timedelta("PT1H")
    index = initialize_index(start=start, end=end, resolution=resolution)

    # 800 kWh: above what one HP can reach (432 kWh), below what two can reach (864 kWh).
    target_soc = 800.0

    shared_result = _run_hp_buffer_scenario(index, target_soc, shared=True)
    separate_result = _run_hp_buffer_scenario(index, target_soc, shared=False)

    shared_cost = shared_result["buffer_min_cost"]
    separate_cost = separate_result["buffer_min_cost"]
    shared_energy = shared_result["energy_cost"]
    separate_energy = separate_result["energy_cost"]

    assert shared_cost == 0, (
        f"Shared buffer: both HPs together can reach {target_soc} kWh, "
        f"so breach cost must be zero (got {shared_cost})"
    )
    assert separate_cost > 0, (
        f"Separate buffers: each HP alone cannot reach {target_soc} kWh, "
        f"so breach cost must be positive (got {separate_cost})"
    )

    # With shared buffer, the optimizer charges exactly 800 kWh combined.
    # Total energy flow = 800 / 0.9 (accounting for charge efficiency).
    assert shared_energy == pytest.approx(target_soc / 0.9 * 100, rel=1e-6)

    # With separate buffers, each HP charges at maximum power for all 24 hours
    # since the 800 kWh individual target is unreachable.
    # Total energy = 2 HPs × 20 kW × 24 h × 100 price.
    assert separate_energy == pytest.approx(2 * 20 * 24 * 100, rel=1e-6)


def make_index(n: int = 5) -> pd.DatetimeIndex:
    """
    Create a simple hourly DatetimeIndex for testing.

    :param n:     Number of hourly periods to generate.
    :return:      DatetimeIndex with `n` hourly timestamps.
    """
    return pd.date_range("2025-01-01", periods=n, freq="h")


def test_any_constant_everything_one_group():
    """
    Verify that when `_type='any'` and all relevant Series
    (quantity, upward price, downward price) remain constant,
    the Commitment assigns all time slots to a single group.
    """
    idx = make_index()
    c = Commitment(
        name="test",
        index=idx,
        _type="any",
        quantity=0,
        upwards_deviation_price=10,
        downwards_deviation_price=-5,
        device=pd.Series("dev", index=idx),
    )
    assert c.group.nunique() == 1
    assert (c.group == 0).all()


def test_any_price_changes_make_new_groups():
    """
    Ensure that changes in either the upward or downward deviation price
    cause the Commitment to start a new group for each contiguous run of
    identical price pairs.
    """
    idx = make_index()
    up = pd.Series([10, 10, 12, 12, 12], index=idx)
    down = pd.Series([-5, -5, -5, -6, -6], index=idx)
    qty = pd.Series(0, index=idx)

    c = Commitment(
        name="test",
        index=idx,
        _type="any",
        quantity=qty,
        upwards_deviation_price=up,
        downwards_deviation_price=down,
        device=pd.Series("dev", index=idx),
    )

    # Expected:
    # t0–t1: same -> group 0
    # t2:    up changes -> group 1
    # t3–t4: down changes -> group 2
    assert list(c.group) == [0, 0, 1, 2, 2]


def test_any_quantity_change_makes_new_group():
    """
    Confirm that changes in the baseline `quantity` Series
    create group boundaries independent of price changes.
    """
    idx = make_index()
    qty = pd.Series([1, 1, 2, 2, 1], index=idx)  # changes at t2 and t4
    up = pd.Series(10, index=idx)
    down = pd.Series(-5, index=idx)

    c = Commitment(
        name="test",
        index=idx,
        _type="any",
        quantity=qty,
        upwards_deviation_price=up,
        downwards_deviation_price=down,
        device=pd.Series("dev", index=idx),
    )

    # Expect boundaries at t2 and t4
    assert list(c.group) == [0, 0, 1, 1, 2]


def test_any_multiple_changes_combined():
    """
    Validate that any change among the three tracked Series
    (quantity, upward price, downward price) triggers a new group,
    and that the Commitment creates maximal contiguous segments.
    """
    idx = make_index()
    qty = pd.Series([0, 0, 1, 1, 2], index=idx)
    up = pd.Series([5, 5, 5, 6, 6], index=idx)
    down = pd.Series([-1, -1, -1, -1, -2], index=idx)

    c = Commitment(
        name="test",
        index=idx,
        _type="any",
        quantity=qty,
        upwards_deviation_price=up,
        downwards_deviation_price=down,
        device=pd.Series("dev", index=idx),
    )

    # t2: qty → new group
    # t3: up → new group
    # t4: down → new group
    assert list(c.group) == [0, 0, 1, 2, 3]


def test_each_type_assigns_unique_group_per_slot():
    """
    Check that `_type='each'` preserves its original semantics:
    every time slot is assigned its own group ID.
    """
    idx = make_index()
    c = Commitment(
        name="test",
        index=idx,
        _type="each",
        quantity=0,
        upwards_deviation_price=1,
        downwards_deviation_price=-1,
        device=pd.Series("dev", index=idx),
    )
    assert list(c.group) == list(range(len(idx)))


def test_two_flexible_assets_with_commodity(app, db):
    """
    Test scheduling two flexible assets (battery + heat pump)
    with explicit electricity commodity.
    """
    # ---- asset types
    battery_type = get_or_create_model(GenericAssetType, name="battery")
    hp_type = get_or_create_model(GenericAssetType, name="heat-pump")

    # ---- time setup
    start = pd.Timestamp("2024-01-01T00:00:00+01:00")
    end = pd.Timestamp("2024-01-02T00:00:00+01:00")
    resolution = pd.Timedelta("1h")

    # ---- assets
    battery = GenericAsset(
        name="Battery (two flexible assets with commodity)",
        generic_asset_type=battery_type,
        attributes={"energy-capacity": "100 kWh"},
    )
    heat_pump = GenericAsset(
        name="Heat Pump",
        generic_asset_type=hp_type,
        attributes={"energy-capacity": "50 kWh"},
    )
    db.session.add_all([battery, heat_pump])
    db.session.commit()

    # ---- sensors
    battery_power = Sensor(
        name="battery power",
        unit="kW",
        event_resolution=resolution,
        generic_asset=battery,
    )
    hp_power = Sensor(
        name="heat pump power",
        unit="kW",
        event_resolution=resolution,
        generic_asset=heat_pump,
    )
    db.session.add_all([battery_power, hp_power])
    db.session.commit()

    # ---- flex-model (list = multi-asset)
    flex_model = [
        {
            # Battery as storage
            "sensor": battery_power.id,
            "commodity": "electricity",
            "soc-at-start": 20.0,
            "soc-min": 0.0,
            "soc-max": 100.0,
            "soc-targets": [{"datetime": "2024-01-01T23:00:00+01:00", "value": 80.0}],
            "power-capacity": "20 kW",
            "charging-efficiency": 0.95,
            "discharging-efficiency": 0.95,
        },
        {
            # Heat pump modeled as storage
            "sensor": hp_power.id,
            "commodity": "electricity",
            "soc-at-start": 10.0,
            "soc-min": 0.0,
            "soc-max": 50.0,
            "soc-targets": [{"datetime": "2024-01-01T23:00:00+01:00", "value": 40.0}],
            "power-capacity": "10 kW",
            "production-capacity": "0 kW",
            "charging-efficiency": 0.95,
        },
    ]

    # ---- flex-context (single electricity market)
    flex_context = {
        "consumption-price": "100 EUR/MWh",
        "production-price": "100 EUR/MWh",
    }

    # ---- run scheduler (use one asset as entry point)
    scheduler = StorageScheduler(
        asset_or_sensor=battery,
        start=start,
        end=end,
        resolution=resolution,
        belief_time=start,
        flex_model=flex_model,
        flex_context=flex_context,
        return_multiple=True,
    )

    schedules = scheduler.compute(skip_validation=True)

    assert isinstance(schedules, list)
    assert (
        len(schedules) == 4
    )  # 2 storage schedules + 1 commitment costs + 1 scheduling_result

    # Extract schedules by type
    storage_schedules = [
        entry for entry in schedules if entry.get("name") == "storage_schedule"
    ]
    commitment_costs = [
        entry for entry in schedules if entry.get("name") == "commitment_costs"
    ]

    assert len(storage_schedules) == 2
    assert len(commitment_costs) == 1

    # Get battery schedule
    battery_schedule = next(
        entry for entry in storage_schedules if entry["sensor"] == battery_power
    )
    battery_data = battery_schedule["data"]

    hp_schedule = next(
        entry for entry in storage_schedules if entry["sensor"] == hp_power
    )
    hp_data = hp_schedule["data"]

    # Verify both devices charge to meet their targets
    assert (battery_data > 0).any(), "Battery should charge at some point"
    assert (hp_data > 0).any(), "Heat pump should charge at some point"

    costs_data = commitment_costs[0]["data"]

    # With net commodity-level results, energy costs are aggregated per commodity
    # Battery: 60kWh Δ (20→80) / 0.95 eff × 100 EUR/MWh ≈ 6.32 EUR (charge) + discharge loss ≈ 4.32 EUR
    # Heat pump: 30kWh Δ (10→40) / 0.95 eff × 100 EUR/MWh ≈ 3.16 EUR (no discharge, prod-cap=0)
    # Total: 4.32 + 3.16 = 7.47 EUR
    electricity_net_energy_cost = costs_data.get("electricity net energy", 0)
    assert electricity_net_energy_cost == pytest.approx(7.47, rel=1e-2), (
        f"Total electricity net energy cost (battery 4.32 + heat pump 3.16): "
        f"= 7.47 EUR, got {electricity_net_energy_cost}"
    )

    # Battery prefers to charge as early as possible (3h @20kW, 1h@>0kW, then 0kW until the last slot with full discharge)
    assert all(battery_data[:3] == 20)
    assert battery_data[3] > 0
    assert all(battery_data[4:-1] == 0)
    assert battery_data[-1] == -20

    # HP prefers to charge as early as possible (3h @10kW, 1h@>0kW, then 0kW)
    assert all(hp_data[:3] == 10)
    assert hp_data[3] > 0
    assert all(hp_data[4:] == 0)

    # ---- RELATIVE COSTS: Battery vs Heat Pump
    # Battery moves 60 kWh, Heat Pump moves 30 kWh (2:1 ratio)
    # Preference costs should reflect this energy ratio
    battery_total_pref = costs_data.get("prefer a full storage 0 sooner", 0)
    hp_total_pref = costs_data.get("prefer a full storage 1 sooner", 0)
    assert battery_total_pref == pytest.approx(2 * hp_total_pref, rel=1e-2), (
        f"Battery preference costs ({battery_total_pref:.2e}) should be twice the "
        f"heat pump ({hp_total_pref:.2e}) preference costs, since battery moves more energy (60 kWh vs 30 kWh)"
    )


def test_mixed_gas_and_electricity_assets(app, db):
    """
    Test scheduling with mixed commodities: battery (electricity) and boiler (gas).
    Verify cost calculations for both commodity types.
    """

    battery_type = get_or_create_model(GenericAssetType, name="battery")
    boiler_type = get_or_create_model(GenericAssetType, name="gas-boiler")

    start = pd.Timestamp("2024-01-01T00:00:00+01:00")
    end = pd.Timestamp("2024-01-02T00:00:00+01:00")
    resolution = pd.Timedelta("1h")

    battery = GenericAsset(
        name="Battery (mixed gas and electricity)",
        generic_asset_type=battery_type,
        attributes={"energy-capacity": "100 kWh"},
    )

    gas_boiler = GenericAsset(
        name="Gas Boiler (mixed gas and electricity)",
        generic_asset_type=boiler_type,
    )

    db.session.add_all([battery, gas_boiler])
    db.session.commit()

    battery_power = Sensor(
        name="battery power",
        unit="kW",
        event_resolution=resolution,
        generic_asset=battery,
    )

    boiler_power = Sensor(
        name="boiler power",
        unit="kW",
        event_resolution=resolution,
        generic_asset=gas_boiler,
    )

    db.session.add_all([battery_power, boiler_power])
    db.session.commit()

    flex_model = [
        {
            # Electricity battery
            "sensor": battery_power.id,
            "commodity": "electricity",
            "soc-at-start": 20.0,
            "soc-min": 0.0,
            "soc-max": 100.0,
            "soc-targets": [{"datetime": "2024-01-01T23:00:00+01:00", "value": 80.0}],
            "power-capacity": "20 kW",
            "charging-efficiency": 0.95,
            "discharging-efficiency": 0.95,
        },
        {
            # Gas-powered device (no storage behavior)
            "sensor": boiler_power.id,
            "commodity": "gas",
            "power-capacity": "30 kW",
            "consumption-capacity": "30 kW",
            "production-capacity": "0 kW",
            "soc-usage": ["1 kW"],
            "soc-min": 0.0,
            "soc-max": 0.0,
            "soc-at-start": 0.0,
        },
    ]

    flex_context = [
        {
            "commodity": "electricity",
            "consumption-price": "100 EUR/MWh",  # electricity price
            "production-price": "100 EUR/MWh",
        },
        {
            "commodity": "gas",
            "consumption-price": "50 EUR/MWh",  # gas price
            "production-price": "50 EUR/MWh",
        },
    ]

    scheduler = StorageScheduler(
        asset_or_sensor=battery,
        start=start,
        end=end,
        resolution=resolution,
        belief_time=start,
        flex_model=flex_model,
        flex_context=flex_context,
        return_multiple=True,
    )

    schedules = scheduler.compute(skip_validation=True)

    assert isinstance(schedules, list)
    assert (
        len(schedules) == 4
    )  # 2 storage schedules + 1 commitment costs + 1 scheduling_result

    # Extract schedules by type
    storage_schedules = [
        entry for entry in schedules if entry.get("name") == "storage_schedule"
    ]
    commitment_costs = [
        entry for entry in schedules if entry.get("name") == "commitment_costs"
    ]

    assert len(storage_schedules) == 2
    assert len(commitment_costs) == 1

    # Get battery schedule
    battery_schedule = next(
        entry for entry in storage_schedules if entry["sensor"] == battery_power
    )
    battery_data = battery_schedule["data"]

    early_charging_hours = battery_data.iloc[:3]
    assert (early_charging_hours > 0).all(), "Battery should charge early"

    assert battery_data.iloc[-1] < 0, "Battery should discharge at the end"

    middle_hours = battery_data.iloc[4:-2]
    assert (middle_hours == 0).all(), "Battery should be idle during middle hours"

    boiler_schedule = next(
        entry for entry in storage_schedules if entry["sensor"] == boiler_power
    )
    boiler_data = boiler_schedule["data"]

    # ---- Verify both devices operate as expected
    assert (battery_data > 0).any(), "Battery should charge at some point"
    assert (boiler_data == 1.0).all(), "Boiler should have constant 1 kW consumption"

    costs_data = commitment_costs[0]["data"]

    # Battery: 60kWh Δ (20→80) / 0.95 eff × 100 EUR/MWh + discharge loss ≈ 4.32 EUR
    # Boiler: constant 1kW × 24h = 24 kWh = 0.024 MWh × 50 EUR/MWh = 1.20 EUR (no efficiency loss)
    # Total: 4.32 + 1.20 = 5.52 EUR
    # With net commodity aggregation, we have separate "electricity net energy" and "gas net energy"
    electricity_net_energy = costs_data.get("electricity net energy", 0)
    gas_net_energy = costs_data.get("gas net energy", 0)

    assert electricity_net_energy == pytest.approx(4.32, rel=1e-2), (
        f"Electricity net energy cost (battery charging phase ~3h at 20kW with 95% efficiency "
        f"+ discharge at end): 60kWh/0.95 × (100 EUR/MWh) = 4.32 EUR, "
        f"got {electricity_net_energy}"
    )

    assert gas_net_energy == pytest.approx(1.20, rel=1e-2), (
        f"Gas net energy cost (boiler constant 1kW for 24h): "
        f"1 kW × 24h = 24 kWh = 0.024 MWh × 50 EUR/MWh = 1.20 EUR, "
        f"got {gas_net_energy}"
    )

    # Total electricity + gas energy costs: battery (4.32) + boiler (1.20) = 5.52 EUR
    total_energy_cost = electricity_net_energy + gas_net_energy
    assert total_energy_cost == pytest.approx(5.52, rel=1e-2), (
        f"Total energy cost (electricity 4.32 + gas 1.20): "
        f"= 5.52 EUR, got {total_energy_cost}"
    )

    # Battery prefers to charge as early as possible (3h @20kW, 1h@>0kW, then 0kW until the last slot with full discharge)
    assert all(battery_data[:3] == 20)
    assert battery_data[3] > 0
    assert all(battery_data[4:-1] == 0)
    assert battery_data[-1] == -20

    # ---- RELATIVE COSTS: Battery vs Boiler (different commodities)
    # Battery has storage flexibility; Boiler is pass-through with constant load
    # Battery preference costs should be higher than boiler's due to flexibility
    battery_total_pref = costs_data.get("prefer a full storage 0 sooner", 0)
    boiler_total_pref = costs_data.get("prefer a full storage 1 sooner", 0)

    assert battery_total_pref > boiler_total_pref, (
        f"Battery preference costs ({battery_total_pref:.2e}) should be greater than "
        f"boiler ({boiler_total_pref:.2e}) preference costs, since battery has storage flexibility "
        f"(can shift charging) while boiler has constant load (no flexibility). "
        f"Ratio: {battery_total_pref / boiler_total_pref:.1f}× (if boiler > 0)"
    )

    # Verify boiler has zero preference cost since it has no flexibility (constant 1 kW)
    assert boiler_total_pref == pytest.approx(0, abs=1e-8), (
        f"Boiler preference cost should be ~0 since it has constant load with no flexibility, "
        f"got {boiler_total_pref:.2e}"
    )

    # Verify battery has positive preference cost from optimizing early fill
    assert battery_total_pref > 0, (
        f"Battery preference cost should be positive since it can optimize charging timing, "
        f"got {battery_total_pref:.2e}"
    )


def test_two_devices_shared_stock(app, db):
    """
    Two feeders charging a single storage.
    Consider a single battery with two inverters feeding it, and a single state-of-charge sensor for the battery.
     - Both inverters can charge the battery, but with different efficiencies.
     - The battery has a single state of charge that both inverters affect.
     - The scheduler should recognize the shared stock and optimize accordingly, without duplicating baselines or costs.
    """
    # ---- time
    start = pd.Timestamp("2024-01-01T00:00:00+01:00")
    end = pd.Timestamp("2024-01-02T00:00:00+01:00")
    power_sensor_resolution = pd.Timedelta("15m")
    soc_sensor_resolution = pd.Timedelta(0)

    # ---- assets
    battery_type = get_or_create_model(GenericAssetType, name="battery")
    inverter_type = get_or_create_model(GenericAssetType, name="inverter")

    battery = GenericAsset(name="battery", generic_asset_type=battery_type)
    inverter_1 = GenericAsset(name="inverter 1", generic_asset_type=inverter_type)
    inverter_2 = GenericAsset(name="inverter 2", generic_asset_type=inverter_type)

    db.session.add_all([battery, inverter_1, inverter_2])
    db.session.commit()

    power_1 = Sensor(
        name="power",
        unit="kW",
        event_resolution=power_sensor_resolution,
        generic_asset=inverter_1,
    )
    power_2 = Sensor(
        name="power",
        unit="kW",
        event_resolution=power_sensor_resolution,
        generic_asset=inverter_2,
    )
    power_3 = Sensor(
        name="power",
        unit="kW",
        event_resolution=power_sensor_resolution,
        generic_asset=battery,
    )

    state_of_charge = Sensor(
        name="state-of-charge",
        unit="kWh",
        event_resolution=soc_sensor_resolution,
        generic_asset=battery,
    )

    db.session.add_all([power_1, power_2, power_3, state_of_charge])
    db.session.commit()

    # ---- shared stock (both batteries charge from same pool)
    flex_model = [
        {
            "sensor": power_1.id,
            "state-of-charge": {"sensor": state_of_charge.id},
            "power-capacity": "20 kW",
            "charging-efficiency": 0.95,
            "discharging-efficiency": 0.95,
        },
        {
            "sensor": power_2.id,
            "state-of-charge": {"sensor": state_of_charge.id},
            "power-capacity": "20 kW",
            "charging-efficiency": 0.99,
            "discharging-efficiency": 0.45,
        },
        {
            "state-of-charge": {"sensor": state_of_charge.id},
            "soc-at-start": 20.0,
            "soc-min": 10,
            "soc-max": 200.0,
            "soc-targets": [{"datetime": "2024-01-01T12:00:00+01:00", "value": 189.0}],
        },
    ]

    flex_context = {
        "consumption-price": "100 EUR/MWh",
        "production-price": "100 EUR/MWh",
    }

    scheduler = StorageScheduler(
        asset_or_sensor=battery,
        start=start,
        end=end,
        resolution=power_sensor_resolution,
        belief_time=start,
        flex_model=flex_model,
        flex_context=flex_context,
        return_multiple=True,
    )

    schedules = scheduler.compute(skip_validation=True)

    # ---- verify scheduler returned expected outputs
    assert isinstance(schedules, list), (
        "Scheduler should return a list of result objects "
        "(device schedules, commitment costs, SOC)."
    )

    assert len(schedules) == 5, (
        "Expected 5 outputs: two inverter schedules, one commitment_costs "
        "object, one state_of_charge schedule, and one scheduling_result."
    )

    # ---- extract schedules
    storage_schedules = [s for s in schedules if s["name"] == "storage_schedule"]
    commitment_costs = [s for s in schedules if s["name"] == "commitment_costs"]
    soc_schedule = next(s for s in schedules if s["name"] == "state_of_charge")

    assert len(storage_schedules) == 2, (
        "There should be two storage schedules corresponding to the two "
        "inverters feeding the shared battery."
    )

    assert (
        len(commitment_costs) == 1
    ), "Commitment costs should be aggregated into a single result."

    power1_schedule = next(s for s in storage_schedules if s["sensor"] == power_1)
    power2_schedule = next(s for s in storage_schedules if s["sensor"] == power_2)

    power1_data = power1_schedule["data"]
    power2_data = power2_schedule["data"]
    soc_data = soc_schedule["data"]
    costs_data = commitment_costs[0]["data"]

    # ---- charging behaviour
    assert (power2_data > 0).any(), (
        "The more efficient inverter should charge the battery at least "
        "during some periods, showing that the optimizer prefers it."
    )

    assert (power1_data == 0).sum() > len(power1_data) * 0.5, (
        "The less efficient inverter should remain idle for most of the "
        "charging window, confirming that efficiency differences influence "
        "device selection."
    )

    # ---- discharge behaviour
    # Both inverters have zero power in the middle of the horizon
    # Charging happens through inverter 2 (more efficient) as soon as possible (full SoC is preferred)
    # Discharging happens through inverter 1 (more efficient) as late as possible (full SoC is preferred)
    assert (
        power1_data.iloc[0 : int(96 / 2 + 13)] == 0
    ).all(), "Inverter 1 should be idle at the beginning of the scheduling period."

    assert (
        power2_data.iloc[int(96 / 2 - 13) : -1] == 0
    ).all(), "Inverter 2 should be idle at the end of the scheduling period."

    # Verify that inverter 1 actually discharges
    assert (power1_data < 0).any(), "Inverter 1 should discharge the battery."
    # Verify that inverter 1 never charges
    assert not (power1_data > 0).any(), "Inverter 1 should not charge the battery."

    # Verify that inverter 2 actually charges
    assert (power2_data > 0).any(), "Inverter 2 should charge the battery."
    # Verify that inverter 1 never charges
    assert not (power2_data < 0).any(), "Inverter 2 should not discharge the battery."

    # ---- SOC behaviour
    assert soc_data.iloc[0] == pytest.approx(
        20.0
    ), "Initial state of charge must match the provided soc-at-start value."

    assert soc_data.max() == pytest.approx(189.0, rel=1e-3), (
        "SOC should rise to exactly 189.0 kWh (the target value), "
        "confirming that both inverters contribute to the same shared stock."
    )

    assert soc_data.iloc[-1] == pytest.approx(
        10.0, rel=1e-3
    ), "SOC should decrease to soc-min (10.0) after the target is reached."

    assert (
        soc_data.max() > soc_data.iloc[0]
    ), "SOC must increase during the charging phase."

    # ---- energy cost checks
    electricity_net_energy_cost = costs_data.get("electricity net energy", 0)
    assert electricity_net_energy_cost == pytest.approx(0.0657, rel=1e-2), (
        "Inverter 1 (discharge efficiency 0.95) discharges ~340 kWh (20 kW for ~40 periods) "
        "from 189 kWh down to 10 kWh (soc-min), incurring discharge losses. "
        "Inverter 2 (charge efficiency 0.99) charges continuously at 20 kW from start until "
        "reaching the soc-target of 189 kWh at 07:30, incurring minimal charge losses. "
        "Net electricity cost of ~0.0657 EUR at 100 EUR/MWh reflects the efficiency difference "
        "between the two inverters specializing in their respective operations."
    )


def set_up_simulation_assets_and_sensors(app, db):
    # ---- asset types and assets
    gas_boiler_type = get_or_create_model(GenericAssetType, name="gas-boiler")
    buffer_type = get_or_create_model(GenericAssetType, name="heat-buffer")
    site_type = get_or_create_model(GenericAssetType, name="site")

    site = GenericAsset(
        name="Test Site",
        generic_asset_type=site_type,
    )
    building = GenericAsset(
        name="Building", generic_asset_type=site_type, parent_asset_id=site.id
    )

    gas_boiler = GenericAsset(
        name="Gas Boiler", generic_asset_type=gas_boiler_type, parent_asset_id=site.id
    )
    heat_buffer = GenericAsset(
        name="Heat Buffer", generic_asset_type=buffer_type, parent_asset_id=site.id
    )
    electric_heater = GenericAsset(
        name="Electric Heater",
        generic_asset_type=get_or_create_model(
            GenericAssetType, name="electric-heater"
        ),
        parent_asset_id=site.id,
    )

    db.session.add_all([gas_boiler, heat_buffer, building, electric_heater, site])
    db.session.commit()

    power_resolution = pd.Timedelta("15m")
    energy_resolution = pd.Timedelta(0)

    building_raw_power = Sensor(
        name="building raw power",
        unit="kW",
        event_resolution=power_resolution,
        generic_asset=building,
    )

    boiler_power = Sensor(
        name="boiler power",
        unit="kW",
        event_resolution=power_resolution,
        generic_asset=gas_boiler,
    )

    tank_power = Sensor(
        name="heat buffer power",
        unit="kW",
        event_resolution=power_resolution,
        generic_asset=heat_buffer,
    )

    buffer_soc = Sensor(
        name="buffer state of charge",
        unit="kWh",
        event_resolution=energy_resolution,  # instantaneous
        generic_asset=heat_buffer,
    )

    buffer_soc_usage = Sensor(
        name="buffer soc usage",
        unit="kW",
        event_resolution=power_resolution,
        generic_asset=heat_buffer,
    )

    heater_power = Sensor(
        name="heater power",
        unit="kW",
        event_resolution=power_resolution,
        generic_asset=electric_heater,
    )
    soc_targets = Sensor(
        name="buffer soc targets",
        unit="kWh",
        event_resolution=energy_resolution,  # instantaneous
        generic_asset=heat_buffer,
    )
    consumption_price = Sensor(
        name="consumption price",
        unit="EUR/MWh",
        event_resolution=energy_resolution,
        generic_asset=site,
    )
    production_price = Sensor(
        name="production price",
        unit="EUR/MWh",
        event_resolution=energy_resolution,
        generic_asset=site,
    )
    gas_price = Sensor(
        name="gas price",
        unit="EUR/MWh",
        event_resolution=energy_resolution,
        generic_asset=site,
    )
    dynamic_consumption_capacity = Sensor(
        name="dynamic consumption capacity",
        unit="kW",
        event_resolution=power_resolution,
        generic_asset=site,
    )

    db.session.add_all(
        [
            boiler_power,
            buffer_soc,
            tank_power,
            buffer_soc_usage,
            building_raw_power,
            heater_power,
            soc_targets,
            consumption_price,
            production_price,
            gas_price,
            dynamic_consumption_capacity,
        ]
    )
    db.session.commit()
    return {
        "site": site,
        "building": building,
        "gas_boiler": gas_boiler,
        "heat_buffer": heat_buffer,
        "electric_heater": electric_heater,
        "building_raw_power": building_raw_power,
        "boiler_power": boiler_power,
        "tank_power": tank_power,
        "buffer_soc": buffer_soc,
        "buffer_soc_usage": buffer_soc_usage,
        "heater_power": heater_power,
        "soc_targets": soc_targets,
        "power_resolution": power_resolution,
        "energy_resolution": energy_resolution,
        "consumption_price": consumption_price,
        "production_price": production_price,
        "gas_price": gas_price,
        "dynamic_consumption_capacity": dynamic_consumption_capacity,
    }


def test_simulation_with_dynamic_consumption_capacity(app, db):

    start = pd.Timestamp("2026-04-07T00:00:00+01:00")
    end = pd.Timestamp(
        "2026-04-09T06:00:00+01:00"
    )  # Extended to allow discharge target on April 8
    belief_time = pd.Timestamp(
        "2026-04-05T00:00:00+01:00"
    )  # 2 days before start for generous planning horizon

    setup_data = set_up_simulation_assets_and_sensors(app, db)

    site = setup_data["site"]
    building_raw_power = setup_data["building_raw_power"]
    heater_power = setup_data["heater_power"]
    boiler_power = setup_data["boiler_power"]
    buffer_soc = setup_data["buffer_soc"]
    buffer_soc_usage = setup_data["buffer_soc_usage"]
    consumption_price = setup_data["consumption_price"]
    gas_price = setup_data["gas_price"]
    dynamic_consumption_capacity = setup_data["dynamic_consumption_capacity"]

    import timely_beliefs as tb
    from flexmeasures import Source

    # add dummy data to building raw power to ensure site-level constraints are respected
    building_data = pd.Series(
        100.0,
        index=pd.date_range(
            start, end, freq=setup_data["power_resolution"], name="event_start"
        ),
        name="event_value",
    ).reset_index()

    soc_usage = building_data.copy()

    bdf = tb.BeliefsDataFrame(
        building_data,
        belief_horizon=-pd.Timedelta(seconds=1) * np.array(range(len(building_data))),
        sensor=setup_data["building_raw_power"],
        source=get_or_create_model(Source, name="Simulation"),
    )
    save_to_db(bdf, bulk_save_objects=False, save_changed_beliefs_only=False)

    # Dynamic site consumption capacity:
    # - 1200 * 0.6 = 720 kW from 12:00 to 18:00
    # - 1200 kW for the rest of the day
    dynamic_capacity_data = pd.DataFrame(
        index=pd.date_range(
            start, end, freq=setup_data["power_resolution"], name="event_start"
        )
    ).reset_index()

    # Dynamic electricity and gas prices:
    # - Electricity is cheaper than gas from 12:00 to 16:00
    # - Gas is cheaper for the rest of the day
    price_index = pd.date_range(
        start,
        end,
        freq=setup_data["power_resolution"],
        name="event_start",
    )

    electricity_price_data = pd.DataFrame(index=price_index).reset_index()
    gas_price_data = pd.DataFrame(index=price_index).reset_index()

    # Default prices: gas cheaper than electricity
    electricity_price_data["event_value"] = 120.0
    gas_price_data["event_value"] = 90.0

    # From 12:00 until before 16:00, electricity cheaper than gas
    cheap_electricity_mask = electricity_price_data["event_start"].dt.hour.between(
        12, 15
    )

    electricity_price_data.loc[
        cheap_electricity_mask,
        "event_value",
    ] = 50.0

    gas_price_data.loc[
        cheap_electricity_mask,
        "event_value",
    ] = 150.0

    bdf = tb.BeliefsDataFrame(
        electricity_price_data,
        belief_time=belief_time,
        sensor=setup_data["consumption_price"],
        source=get_or_create_model(Source, name="Simulation"),
    )
    save_to_db(bdf, bulk_save_objects=False, save_changed_beliefs_only=False)

    bdf = tb.BeliefsDataFrame(
        gas_price_data,
        belief_time=belief_time,
        sensor=setup_data["gas_price"],
        source=get_or_create_model(Source, name="Simulation"),
    )
    save_to_db(bdf, bulk_save_objects=False, save_changed_beliefs_only=False)

    dynamic_capacity_data["event_value"] = 100.0

    dynamic_capacity_data.loc[
        dynamic_capacity_data["event_start"].dt.hour.between(12, 17),
        "event_value",
    ] = (
        100.0 * 0.6
    )

    bdf = tb.BeliefsDataFrame(
        dynamic_capacity_data,
        belief_time=belief_time,
        sensor=setup_data["dynamic_consumption_capacity"],
        source=get_or_create_model(Source, name="Simulation"),
    )

    save_to_db(bdf, bulk_save_objects=False, save_changed_beliefs_only=False)

    soc_usage["event_value"] = 100
    bdf = tb.BeliefsDataFrame(
        soc_usage,
        belief_time=belief_time,
        sensor=setup_data["buffer_soc_usage"],
        source=get_or_create_model(Source, name="Simulation"),
    )

    save_to_db(bdf, bulk_save_objects=False, save_changed_beliefs_only=False)

    flex_model = [
        {
            "sensor": heater_power.id,
            "state-of-charge": {"sensor": buffer_soc.id},
            "power-capacity": "100 kW",
            "charging-efficiency": 0.9,
            "commodity": "electricity",
            "production-capacity": "0 kW",
        },
        {
            "sensor": boiler_power.id,
            "state-of-charge": {"sensor": buffer_soc.id},
            "power-capacity": "100 kW",
            "charging-efficiency": 0.9,
            "commodity": "gas",
            "production-capacity": "0 kW",
        },
        {
            # "sensor": tank_power.id,
            "soc-min": 200.0,
            "soc-max": 1000.0,
            "soc-at-start": 200.0,
            # "soc-targets": [
            #     {"datetime": "2026-04-07T20:00:00+01:00", "value": 700.0},
            # ],
            "state-of-charge": {"sensor": buffer_soc.id},
            "soc-usage": [{"sensor": buffer_soc_usage.id}],
            "storage-efficiency": "99%",  # the buffer leaks 1% of its stock every 15 minutes
            # todo: consider assigning this to the heat commodity, maybe we can derive some useful (costs?) KPI from it
        },
    ]

    flex_context = {
        "commodities": [
            {
                "commodity": "electricity",
                "consumption-price": {
                    "sensor": consumption_price.id,
                },
                "production-price": {
                    "sensor": consumption_price.id,
                },
                "site-power-capacity": "1900 kW",
                "site-consumption-capacity": {
                    "sensor": dynamic_consumption_capacity.id,
                },
                "site-production-capacity": "100 kW",
                "site-consumption-breach-price": "100000 EUR/kW",
                "site-production-breach-price": "100000 EUR/kW",
                "inflexible-device-sensors": [building_raw_power.id],
            },
            {
                "commodity": "gas",
                "consumption-price": {
                    "sensor": gas_price.id,
                },
                "production-price": {
                    "sensor": gas_price.id,
                },
                # No electricity dynamic capacity here.
                "site-consumption-capacity": "100000 kW",
                "inflexible-device-sensors": [building_raw_power.id],
            },
        ],
        "relax-constraints": True,
    }

    scheduler = StorageScheduler(
        asset_or_sensor=site,
        start=start,
        end=end,
        resolution=setup_data["power_resolution"],
        belief_time=belief_time,
        flex_model=flex_model,
        flex_context=flex_context,
        return_multiple=True,
    )

    schedules = scheduler.compute(skip_validation=True)

    heater_schedule = next(
        schedule["data"]
        for schedule in schedules
        if schedule.get("sensor") == heater_power
    )

    boiler_schedule = next(
        schedule["data"]
        for schedule in schedules
        if schedule.get("sensor") == boiler_power
    )
    # In local time, electricity is cheaper from 12:00 to 16:00.
    # During this period, the dynamic electricity site capacity is only 60 kW.
    # Therefore, the electric heater is expected to run at 60 kW, not its full
    # 100 kW device capacity.
    pd.testing.assert_series_equal(
        heater_schedule.loc["2026-04-07T11:00:00+00:00":"2026-04-07T14:45:00+00:00"],
        pd.Series(
            60.0,
            index=pd.date_range(
                "2026-04-07T11:00:00+00:00",
                "2026-04-07T14:45:00+00:00",
                freq="15min",
            ),
            dtype="float64",
        ),
        check_names=False,
        obj=(
            "electric heater dispatch during cheap-electricity window on day 1; "
            "expected 60 kW because dynamic electricity capacity limits the heater"
        ),
    )

    # When electricity is cheaper than gas, the gas boiler should stay off,
    # with the heat demand supplied by the electric heater instead. Only near
    # the end of the window does the boiler top up the heat buffer: the 60 kW
    # electricity capacity cannot cover demand plus the buffer's storage losses
    # for the whole window, and topping up as late as possible leaks the least.
    pd.testing.assert_series_equal(
        boiler_schedule.loc["2026-04-07T11:00:00+00:00":"2026-04-07T13:45:00+00:00"],
        pd.Series(
            0.0,
            index=pd.date_range(
                "2026-04-07T11:00:00+00:00",
                "2026-04-07T13:45:00+00:00",
                freq="15min",
            ),
            dtype="float64",
        ),
        check_names=False,
        obj=(
            "gas boiler dispatch during cheap-electricity window on day 1; "
            "expected 0 kW because electricity is cheaper than gas"
        ),
    )
    np.testing.assert_allclose(
        boiler_schedule.loc["2026-04-07T14:00:00+00:00":"2026-04-07T14:45:00+00:00"],
        60.044743,
        atol=1e-3,
        err_msg="Gas boiler should top up the heat buffer in the final hour of the cheap-electricity window on day 1.",
    )

    pd.testing.assert_series_equal(
        heater_schedule.loc["2026-04-08T11:00:00+00:00":"2026-04-08T14:45:00+00:00"],
        pd.Series(
            60.0,
            index=pd.date_range(
                "2026-04-08T11:00:00+00:00",
                "2026-04-08T14:45:00+00:00",
                freq="15min",
            ),
            dtype="float64",
        ),
        check_names=False,
        obj=(
            "electric heater dispatch during cheap-electricity window on day 2; "
            "expected 60 kW because dynamic electricity capacity limits the heater"
        ),
    )

    pd.testing.assert_series_equal(
        boiler_schedule.loc["2026-04-08T11:00:00+00:00":"2026-04-08T13:45:00+00:00"],
        pd.Series(
            0.0,
            index=pd.date_range(
                "2026-04-08T11:00:00+00:00",
                "2026-04-08T13:45:00+00:00",
                freq="15min",
            ),
            dtype="float64",
        ),
        check_names=False,
        obj=(
            "gas boiler dispatch during cheap-electricity window on day 2; "
            "expected 0 kW because electricity is cheaper than gas"
        ),
    )
    np.testing.assert_allclose(
        boiler_schedule.loc["2026-04-08T14:00:00+00:00":"2026-04-08T14:45:00+00:00"],
        60.044743,
        atol=1e-3,
        err_msg="Gas boiler should top up the heat buffer in the final hour of the cheap-electricity window on day 2.",
    )

    # Outside the cheap-electricity window, gas is cheaper than electricity.
    # Therefore, the gas boiler should become the preferred heat source and run
    # at full 100 kW capacity. The pricier electric heater cannot switch off
    # entirely, though: the buffer's storage losses push the total heat need
    # beyond the boiler's capacity, so the heater covers the remainder.
    assert boiler_schedule.loc["2026-04-07T15:00:00+00:00"] == pytest.approx(
        100.0
    ), "Gas boiler should run at full capacity after the cheap-electricity window on day 1."

    assert heater_schedule.loc["2026-04-07T15:00:00+00:00"] == pytest.approx(
        20.044743, abs=1e-3
    ), "Electric heater should only cover what the maxed-out gas boiler cannot, after the cheap-electricity window on day 1."

    assert boiler_schedule.loc["2026-04-08T15:00:00+00:00"] == pytest.approx(
        100.0
    ), "Gas boiler should run at full capacity after the cheap-electricity window on day 2."

    assert heater_schedule.loc["2026-04-08T15:00:00+00:00"] == pytest.approx(
        20.044743, abs=1e-3
    ), "Electric heater should only cover what the maxed-out gas boiler cannot, after the cheap-electricity window on day 2."

    # Before the first cheap-electricity window, the optimizer ramps up the
    # electric heater (one partial step, then full 100 kW capacity) to prepare
    # the heat buffer. This is part of the expected optimal schedule and
    # protects against accidental dispatch changes.
    assert heater_schedule.loc["2026-04-07T08:15:00+00:00"] == pytest.approx(
        25.713284, abs=1e-3
    ), "Electric heater should have one expected partial dispatch step before ramping up to prepare for the first cheap-electricity window."
    assert heater_schedule.loc["2026-04-07T08:30:00+00:00"] == pytest.approx(
        100.0
    ), "Electric heater should charge the heat buffer at full capacity just before the first cheap-electricity window."


def test_all_gas_flex_model_without_electricity_device(app, db):
    """test_all_gas_flex_model_without_electricity_device: a flex-model with only gas
    devices (no electricity device at all) should not raise a KeyError, now that
    commodity_to_devices["electricity"] is built with setdefault().
    """
    boiler_type = get_or_create_model(GenericAssetType, name="gas-boiler")

    start = pd.Timestamp("2024-01-01T00:00:00+01:00")
    end = pd.Timestamp("2024-01-02T00:00:00+01:00")
    resolution = pd.Timedelta("1h")

    gas_boiler = GenericAsset(
        name="Gas Boiler (all-gas flex-model test)",
        generic_asset_type=boiler_type,
    )
    db.session.add(gas_boiler)
    db.session.commit()

    boiler_power = Sensor(
        name="boiler power",
        unit="kW",
        event_resolution=resolution,
        generic_asset=gas_boiler,
    )
    db.session.add(boiler_power)
    db.session.commit()

    flex_model = [
        {
            "sensor": boiler_power.id,
            "commodity": "gas",
            "power-capacity": "30 kW",
            "consumption-capacity": "30 kW",
            "production-capacity": "0 kW",
            "soc-usage": ["1 kW"],
            "soc-min": 0.0,
            "soc-max": 0.0,
            "soc-at-start": 0.0,
        },
    ]

    flex_context = [
        {
            "commodity": "gas",
            "consumption-price": "50 EUR/MWh",
            "production-price": "50 EUR/MWh",
        },
    ]

    scheduler = StorageScheduler(
        asset_or_sensor=gas_boiler,
        start=start,
        end=end,
        resolution=resolution,
        belief_time=start,
        flex_model=flex_model,
        flex_context=flex_context,
        return_multiple=True,
    )

    # This used to raise KeyError("electricity") in _prepare().
    schedules = scheduler.compute(skip_validation=True)

    storage_schedules = [
        entry for entry in schedules if entry.get("name") == "storage_schedule"
    ]
    assert len(storage_schedules) == 1
    boiler_schedule = storage_schedules[0]["data"]
    assert (boiler_schedule == 1.0).all()


def test_per_commodity_inflexible_device_sensors(app, db):
    """test_per_commodity_inflexible_device_sensors: an inflexible-device-sensor declared
    inside a (non-electricity) commodity context should constrain that commodity's site
    capacity and be reflected in the flexible device's schedule (since its consumption
    capacity leaves no room for the inflexible load plus more).
    """
    boiler_type = get_or_create_model(GenericAssetType, name="gas-boiler")

    start = pd.Timestamp("2024-01-01T00:00:00+01:00")
    end = pd.Timestamp("2024-01-01T04:00:00+01:00")
    resolution = pd.Timedelta("1h")

    gas_site = GenericAsset(
        name="Gas Site (per-commodity inflexible sensor test)",
        generic_asset_type=boiler_type,
    )
    db.session.add(gas_site)
    db.session.commit()

    flexible_boiler_power = Sensor(
        name="flexible boiler power",
        unit="kW",
        event_resolution=resolution,
        generic_asset=gas_site,
    )
    inflexible_gas_load = Sensor(
        name="inflexible gas load",
        unit="kW",
        event_resolution=resolution,
        generic_asset=gas_site,
    )
    gas_aggregate_consumption = Sensor(
        name="gas aggregate consumption",
        unit="kW",
        event_resolution=resolution,
        generic_asset=gas_site,
    )
    db.session.add_all(
        [flexible_boiler_power, inflexible_gas_load, gas_aggregate_consumption]
    )
    db.session.commit()

    # A constant 8 kW inflexible gas load, recorded as beliefs.
    # By default, power sensors store consumption as negative values
    # (get_power_values flips the sign to the scheduler's consumption-positive convention).
    index = initialize_index(start, end, resolution)

    source = get_or_create_model(DataSource, name="test source", type="forecaster")
    beliefs = [
        TimedBelief(
            sensor=inflexible_gas_load,
            source=source,
            event_start=dt,
            belief_time=start,
            event_value=-8.0,
        )
        for dt in index
    ]
    db.session.add_all(beliefs)
    db.session.commit()

    flex_model = [
        {
            "sensor": flexible_boiler_power.id,
            "commodity": "gas",
            "power-capacity": "30 kW",
            "consumption-capacity": "30 kW",
            "production-capacity": "0 kW",
            "soc-usage": ["1 kW"],
            "soc-min": 0.0,
            "soc-max": 0.0,
            "soc-at-start": 0.0,
        },
    ]

    flex_context = [
        {
            "commodity": "gas",
            "consumption-price": "50 EUR/MWh",
            "production-price": "50 EUR/MWh",
            "site-consumption-capacity": "10 kW",
            "inflexible-device-sensors": [inflexible_gas_load.id],
            "aggregate-consumption": {"sensor": gas_aggregate_consumption.id},
        },
    ]

    scheduler = StorageScheduler(
        asset_or_sensor=gas_site,
        start=start,
        end=end,
        resolution=resolution,
        belief_time=start,
        flex_model=flex_model,
        flex_context=flex_context,
        return_multiple=True,
    )

    schedules = scheduler.compute(skip_validation=True)

    storage_schedules = [
        entry for entry in schedules if entry.get("name") == "storage_schedule"
    ]
    boiler_schedule = next(
        entry for entry in storage_schedules if entry["sensor"] == flexible_boiler_power
    )["data"]

    # With an 8 kW inflexible gas load counted against the 10 kW site-consumption-capacity,
    # the flexible boiler (which otherwise consumes a constant 1 kW) is left at most 2 kW of
    # headroom.
    assert (boiler_schedule <= 2.0 + 1e-6).all()

    # The aggregate-consumption schedule for the gas commodity must include the inflexible
    # gas load. Before the fix, the per-commodity inflexible sensor got no device constraints
    # (its device index was silently dropped), so the aggregate would only reflect the
    # flexible boiler's ~1 kW instead of 8 + 1 = 9 kW.
    aggregate_schedule = next(
        entry
        for entry in storage_schedules
        if entry["sensor"] == gas_aggregate_consumption
    )["data"]
    expected_aggregate = boiler_schedule + 8.0
    assert aggregate_schedule.values == pytest.approx(
        expected_aggregate.values, abs=1e-6
    ), (
        "Aggregate gas consumption should include the 8 kW inflexible gas load "
        "on top of the flexible boiler's schedule."
    )


def test_electricity_device_indices_exclude_other_commodities():
    """test_electricity_device_indices_exclude_other_commodities: the device indices used
    for the aggregate-power sum should cover only electricity devices (flexible and
    inflexible), not gas devices, nor per-commodity inflexible devices of other commodities.
    """
    scheduler = object.__new__(StorageScheduler)
    # Flexible devices: 0 = electricity, 1 = gas, 2 = electricity (implicit default)
    scheduler._device_models = [
        {"commodity": "electricity"},
        {"commodity": "gas"},
        {},  # defaults to electricity
    ]
    scheduler.flex_model = scheduler._device_models
    # Top-level inflexible sensors (electricity): indices 3 and 4.
    # Gas commodity context with one inflexible sensor: index 5.
    scheduler.flex_context = {
        "inflexible_device_sensors": ["el_sensor_a", "el_sensor_b"],
        "commodity_contexts": [
            {"commodity": "gas", "inflexible_device_sensors": ["gas_sensor"]},
        ],
    }

    mapping = scheduler._reconstruct_commodity_to_devices()
    assert mapping["electricity"] == [0, 2, 3, 4]
    assert mapping["gas"] == [1, 5]
    assert scheduler._electricity_device_indices() == [0, 2, 3, 4]


def _shared_stock_scheduler(db, flex_model, label):
    """Set up a battery with two inverter power sensors and one SoC sensor.

    The passed flex_model receives the sensor references via format placeholders
    ``power_1``, ``power_2`` and ``soc``.
    """
    start = pd.Timestamp("2024-01-01T00:00:00+01:00")
    end = pd.Timestamp("2024-01-02T00:00:00+01:00")
    resolution = pd.Timedelta("15m")

    battery_type = get_or_create_model(GenericAssetType, name="battery")
    inverter_type = get_or_create_model(GenericAssetType, name="inverter")
    battery = GenericAsset(
        name=f"storage-efficiency test battery {label}", generic_asset_type=battery_type
    )
    inverter_1 = GenericAsset(
        name=f"storage-efficiency test inverter 1 {label}",
        generic_asset_type=inverter_type,
    )
    inverter_2 = GenericAsset(
        name=f"storage-efficiency test inverter 2 {label}",
        generic_asset_type=inverter_type,
    )
    db.session.add_all([battery, inverter_1, inverter_2])
    power_1 = Sensor(
        name="power", unit="kW", event_resolution=resolution, generic_asset=inverter_1
    )
    power_2 = Sensor(
        name="power", unit="kW", event_resolution=resolution, generic_asset=inverter_2
    )
    soc = Sensor(
        name="state-of-charge",
        unit="kWh",
        event_resolution=pd.Timedelta(0),
        generic_asset=battery,
    )
    db.session.add_all([power_1, power_2, soc])
    db.session.commit()

    power_sensors = {"power_1": power_1.id, "power_2": power_2.id}
    for entry in flex_model:
        if "sensor" in entry:
            entry["sensor"] = power_sensors[entry["sensor"]]
        if "state-of-charge" in entry:
            entry["state-of-charge"] = {"sensor": soc.id}

    return StorageScheduler(
        asset_or_sensor=battery,
        start=start,
        end=end,
        resolution=resolution,
        belief_time=start,
        flex_model=flex_model,
        flex_context={
            "consumption-price": "100 EUR/MWh",
            "production-price": "100 EUR/MWh",
        },
        return_multiple=True,
    )


def test_shared_stock_storage_efficiency_applies_to_all_members(db):
    """A storage-efficiency defined on the stock's SoC-parameters entry applies to every member device."""
    scheduler = _shared_stock_scheduler(
        db,
        [
            {"sensor": "power_1", "state-of-charge": "soc", "power-capacity": "20 kW"},
            {"sensor": "power_2", "state-of-charge": "soc", "power-capacity": "20 kW"},
            {
                "state-of-charge": "soc",
                "soc-at-start": 20.0,
                "soc-min": 10,
                "soc-max": 200.0,
                "storage-efficiency": "99%",
            },
        ],
        label="propagate",
    )
    device_constraints = scheduler._prepare(skip_validation=True)[5]
    assert (device_constraints[0]["efficiency"] == 0.99).all()
    assert device_constraints[1]["efficiency"].equals(
        device_constraints[0]["efficiency"]
    )


def test_shared_stock_storage_efficiency_defined_twice_fails(db):
    """Two entries defining a storage-efficiency for the same stock are rejected."""
    scheduler = _shared_stock_scheduler(
        db,
        [
            {
                "sensor": "power_1",
                "state-of-charge": "soc",
                "power-capacity": "20 kW",
                "storage-efficiency": "99%",
            },
            {
                "sensor": "power_2",
                "state-of-charge": "soc",
                "power-capacity": "20 kW",
                "storage-efficiency": "99%",
            },
            {
                "state-of-charge": "soc",
                "soc-at-start": 20.0,
                "soc-min": 10,
                "soc-max": 200.0,
            },
        ],
        label="conflict",
    )
    with pytest.raises(ValueError, match="define it on a single entry"):
        scheduler._prepare(skip_validation=True)


@pytest.mark.parametrize("named_device", [0, 1])
def test_stock_scoped_commitment_binds_group_stock(named_device):
    """A stock-scoped StockCommitment binds its stock group as a whole,
    regardless of which member device index it names."""
    start = pd.Timestamp("2026-01-01T00:00+01")
    end = pd.Timestamp("2026-01-01T04:00+01")
    resolution = pd.Timedelta("PT1H")
    index = initialize_index(start=start, end=end, resolution=resolution)

    device_constraints = [
        pd.DataFrame(
            {
                "min": 0.0,
                "max": 100.0,
                "equals": np.nan,
                "derivative min": 0.0,
                "derivative max": 10.0,
                "derivative equals": np.nan,
                "derivative down efficiency": 1.0,
                "derivative up efficiency": 1.0,
            },
            index=index,
        )
        for _ in range(2)
    ]
    ems_constraints = pd.DataFrame(
        {"derivative min": -100, "derivative max": 100}, index=index
    )

    # Require the shared stock to hold 20 units at the end of the horizon.
    min_stock = pd.Series(0.0, index=index)
    min_stock.iloc[-1] = 20.0

    commitments = [
        StockCommitment(
            name="soc minimum",
            index=index,
            quantity=min_stock,
            downwards_deviation_price=-1000,
            device=named_device,
            stock=7,
        ),
    ] + [
        FlowCommitment(
            name=f"energy device {d}",
            index=index,
            quantity=0,
            upwards_deviation_price=10,
            downwards_deviation_price=10,
            device=pd.Series(d, index=index),
        )
        for d in (0, 1)
    ]

    planned_power, planned_costs, results, model = device_scheduler(
        device_constraints=device_constraints,
        ems_constraints=ems_constraints,
        commitments=commitments,
        initial_stock=0,
        stock_groups={7: [0, 1]},
    )

    assert results.solver.termination_condition == "optimal"
    # Charging just enough to meet the stock minimum beats paying the breach price,
    # so the group's total stock change reaches exactly 20 - no matter whether the
    # commitment named the group's first or second device.
    total_energy = sum(schedule.sum() for schedule in planned_power)
    np.testing.assert_allclose(total_energy, 20.0, atol=1e-6)
