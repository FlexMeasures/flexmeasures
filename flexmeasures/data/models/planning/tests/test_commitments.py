import pytest
import pandas as pd
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
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.planning.linear_optimization import device_scheduler
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType


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
        name="Battery",
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
    assert len(schedules) == 3  # 2 storage schedules + 1 commitment costs

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

    # Get heat pump schedule
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
        name="Battery",
        generic_asset_type=battery_type,
        attributes={"energy-capacity": "100 kWh"},
    )

    gas_boiler = GenericAsset(
        name="Gas Boiler",
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

    flex_context = {
        "consumption-price": "100 EUR/MWh",  # electricity price
        "production-price": "100 EUR/MWh",
        "gas-price": "50 EUR/MWh",  # gas price
    }

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
    assert len(schedules) == 3  # 2 storage schedules + 1 commitment costs

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
