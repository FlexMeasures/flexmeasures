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
from flexmeasures.data.models.time_series import Sensor
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

    assert len(schedules) == 4, (
        "Expected 4 outputs: two inverter schedules, one commitment_costs "
        "object, and one state_of_charge schedule."
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
            # "storage-efficiency": 0.9,  # todo: workaround does not work yet
        },
        {
            "sensor": boiler_power.id,
            "state-of-charge": {"sensor": buffer_soc.id},
            "power-capacity": "100 kW",
            "charging-efficiency": 0.9,
            "commodity": "gas",
            "production-capacity": "0 kW",
            # "storage-efficiency": 0.9,  # todo: workaround does not work yet
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
            "storage-efficiency": 0.9,  # todo: does not work yet
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
    # The electric heater should only be active in the cheap-electricity window.
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

    # When electricity is cheaper than gas, the gas boiler should stay off.
    # The heat demand is then supplied by the electric heater instead.
    pd.testing.assert_series_equal(
        boiler_schedule.loc["2026-04-07T11:00:00+00:00":"2026-04-07T14:45:00+00:00"],
        pd.Series(
            0.0,
            index=pd.date_range(
                "2026-04-07T11:00:00+00:00",
                "2026-04-07T14:45:00+00:00",
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
        boiler_schedule.loc["2026-04-08T11:00:00+00:00":"2026-04-08T14:45:00+00:00"],
        pd.Series(
            0.0,
            index=pd.date_range(
                "2026-04-08T11:00:00+00:00",
                "2026-04-08T14:45:00+00:00",
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

    # Outside the cheap-electricity window, gas is cheaper than electricity.
    # Therefore, the gas boiler should become the preferred heat source and run
    # at full 100 kW capacity, while the electric heater should remain off.
    assert boiler_schedule.loc["2026-04-07T15:00:00+00:00"] == pytest.approx(
        100.0
    ), "Gas boiler should run at full capacity after the cheap-electricity window on day 1."

    assert heater_schedule.loc["2026-04-07T15:00:00+00:00"] == pytest.approx(
        0.0
    ), "Electric heater should be off after the cheap-electricity window because gas is cheaper."

    assert boiler_schedule.loc["2026-04-08T15:00:00+00:00"] == pytest.approx(
        100.0
    ), "Gas boiler should run at full capacity after the cheap-electricity window on day 2."

    assert heater_schedule.loc["2026-04-08T15:00:00+00:00"] == pytest.approx(
        0.0
    ), "Electric heater should be off after the cheap-electricity window on day 2 because gas is cheaper."

    # Before the first cheap-electricity window, the optimizer uses a partial
    # 80 kW electric-heater step to prepare the heat buffer. This is part of the
    # expected optimal schedule and protects against accidental dispatch changes.
    assert heater_schedule.loc["2026-04-07T08:00:00+00:00"] == pytest.approx(
        80.0
    ), "Electric heater should have one expected partial 80 kW dispatch step before the first cheap-electricity window."


def test_chp_coupling():
    """Test that coupling_groups enforces fixed flow ratios between CHP devices.

    Models a Combined Heat and Power unit with three flow devices:

    - d=0  gas input:    can only consume gas          (derivative_min=0)
    - d=1  heat output:  can only produce heat          (derivative_max=0)
    - d=2  power output: can only produce electricity   (derivative_max=0)

    The coupling group ``"chp"`` is specified with coefficients
    ``[(0, 1.0), (1, -0.5), (2, -0.3)]``. This generates two hard equality
    constraints for every time step ``j``:

        1.0 * P_gas[j]  ==  -0.5 * P_heat[j]   →  P_gas  == -0.5 * P_heat
        1.0 * P_gas[j]  ==  -0.3 * P_power[j]  →  P_gas  == -0.3 * P_power

    Heat production is forced to exactly 10 kW via ``derivative equals = -10``
    on device 1. Substituting into the coupling constraints gives the expected
    solution:

        P_gas   =  5 kW          (gas consumed)
        P_heat  = -10 kW         (heat produced, forced)
        P_power = -50/3 ≈ -16.67 kW  (electricity produced)

    Note: the coefficients above do not represent a physically realisable CHP
    (total output exceeds input). They are chosen to exercise the constraint
    arithmetic with non-trivial numbers that are easy to verify by hand.
    """
    start = pd.Timestamp("2026-01-01T00:00+01:00")
    end = pd.Timestamp("2026-01-01T04:00+01:00")
    resolution = pd.Timedelta("1h")
    index = initialize_index(start=start, end=end, resolution=resolution)

    # d=0: gas input — can only consume (derivative_min=0), capacity 100 kW.
    # NaN stock bounds mean no cumulative-stock constraint (pure flow device).
    gas_constraints = pd.DataFrame(
        {
            "min": np.nan,
            "max": np.nan,
            "equals": np.nan,
            "derivative min": 0.0,
            "derivative max": 100.0,
            "derivative equals": np.nan,
            "derivative down efficiency": 1.0,
            "derivative up efficiency": 1.0,
        },
        index=index,
    )

    # d=1: heat output — can only produce (derivative_max=0).
    # Forced to exactly -10 kW via derivative equals.
    heat_constraints = pd.DataFrame(
        {
            "min": np.nan,
            "max": np.nan,
            "equals": np.nan,
            "derivative min": -100.0,
            "derivative max": 0.0,
            "derivative equals": -10.0,
            "derivative down efficiency": 1.0,
            "derivative up efficiency": 1.0,
        },
        index=index,
    )

    # d=2: power output — can only produce (derivative_max=0), capacity 100 kW.
    # Flow is free; the coupling constraint will determine its value.
    power_constraints = pd.DataFrame(
        {
            "min": np.nan,
            "max": np.nan,
            "equals": np.nan,
            "derivative min": -100.0,
            "derivative max": 0.0,
            "derivative equals": np.nan,
            "derivative down efficiency": 1.0,
            "derivative up efficiency": 1.0,
        },
        index=index,
    )

    ems_constraints = pd.DataFrame(
        {"derivative min": -200.0, "derivative max": 200.0},
        index=index,
    )

    # Coupling group: one reference device (gas, coeff 1.0) and two coupled
    # devices (heat with coeff -0.5, power with coeff -0.3).
    coupling_groups = {"chp": [(0, 1.0), (1, -0.5), (2, -0.3)]}

    # Gas-price commitment gives the objective a finite value and models the
    # cost of consuming gas. With quantity=0 and both prices set the
    # commitment acts as a two-sided soft equality: any upward deviation
    # (gas consumption) incurs a cost of 1 EUR/kW.
    gas_price_commitment = FlowCommitment(
        name="gas cost",
        index=index,
        quantity=pd.Series(0.0, index=index),
        upwards_deviation_price=pd.Series(1.0, index=index),
        downwards_deviation_price=pd.Series(0.0, index=index),
        device=pd.Series(0, index=index),
    )

    schedules, planned_costs, results, model = device_scheduler(
        device_constraints=[gas_constraints, heat_constraints, power_constraints],
        ems_constraints=ems_constraints,
        commitments=[gas_price_commitment],
        coupling_groups=coupling_groups,
    )

    assert (
        results.solver.termination_condition == "optimal"
    ), "Solver did not find an optimal solution."

    # Heat is fixed to -10 kW by derivative_equals.
    pd.testing.assert_series_equal(
        schedules[1],
        pd.Series(-10.0, index=index),
        check_names=False,
        rtol=1e-4,
        obj="heat output forced to -10 kW by derivative_equals",
    )

    # Coupling: 1.0 * P_gas == -0.5 * P_heat  →  P_gas = -0.5 * (-10) = 5 kW
    pd.testing.assert_series_equal(
        schedules[0],
        pd.Series(5.0, index=index),
        check_names=False,
        rtol=1e-4,
        obj="gas consumption determined by coupling (5 kW from 10 kW heat at coeff -0.5)",
    )

    # Coupling: 1.0 * P_gas == -0.3 * P_power  →  P_power = -5 / 0.3 = -50/3 kW
    pd.testing.assert_series_equal(
        schedules[2],
        pd.Series(-50.0 / 3.0, index=index),
        check_names=False,
        rtol=1e-4,
        obj="power output determined by coupling (-50/3 kW from 5 kW gas at coeff -0.3)",
    )


def _run_factory_scenario(
    gas_price: float,
    elec_price: float,
) -> tuple:
    """Run the simplified factory scenario and return the 6 device schedules.

    Layout
    ------
    The model collapses the heat buffer (T) and steam node (P) into a single
    shared heat buffer whose SoC is tracked by ``stock_groups``. The steam
    demand is an exogenous drain modelled as ``stock_delta = -steam_demand`` on
    the demand device (d=5).

    Devices
    ~~~~~~~
    d=0  e-heater       electricity → heat buffer   (ems_power ≥ 0)
    d=1  gas boiler     gas         → heat buffer   (ems_power ≥ 0)
    d=2  CHP gas input  consumes gas                (ems_power ≥ 0, coupling ref)
    d=3  CHP heat out   heat → heat buffer          (ems_power ≥ 0, coupling member)
    d=4  CHP power out  produces electricity        (ems_power ≤ 0, coupling member)
    d=5  steam demand   fixed drain, no flow        (ems_power = 0, stock_delta = -15)

    CHP coupling coefficients
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    The coupling constraint is built from the general pairwise equality::

        coeff_ref * P[d_ref] == coeff_i * P[d_i]

    Choosing d_ref = 2 (gas input, coeff 1.0) and thermal efficiency η_heat = 0.5,
    power efficiency η_power = 0.3::

        P_heat  = η_heat  * P_gas  = 0.5 * P_gas
        P_power = -η_power * P_gas = -0.3 * P_gas

    Solving for the coupling coefficients::

        1.0 * P_gas = coeff_heat  * P_heat   → coeff_heat  = 1/η_heat  = 2.0
        1.0 * P_gas = coeff_power * P_power  → coeff_power = -1/η_power = -10/3

    Note: both d=2 and d=3 have *positive* ems_power (they both "consume" from
    their respective commodity nodes, which causes the stock accumulation formula
    to add a positive contribution to the heat buffer for d=3). d=4 has
    *negative* ems_power (it produces electricity), so coeff_power is negative.
    """
    ETA_HEAT = 0.5  # fraction of CHP gas input that becomes heat
    ETA_POWER = 0.3  # fraction of CHP gas input that becomes power
    STEAM_DEMAND = 15.0  # kW, constant heat drain representing steam production
    CHP_GAS_MAX = 20.0  # kW, maximum gas input to CHP

    start = pd.Timestamp("2026-01-01T00:00+01:00")
    end = pd.Timestamp("2026-01-01T04:00+01:00")
    resolution = pd.Timedelta("1h")
    index = initialize_index(start=start, end=end, resolution=resolution)

    def _df(**kwargs) -> pd.DataFrame:
        """Build a device-constraints DataFrame with defaults for unused columns."""
        defaults = {
            "min": np.nan,
            "max": np.nan,
            "equals": np.nan,
            "derivative min": 0.0,
            "derivative max": 0.0,
            "derivative equals": np.nan,
            "derivative down efficiency": 1.0,
            "derivative up efficiency": 1.0,
            "stock delta": 0.0,
        }
        defaults.update(kwargs)
        return pd.DataFrame(defaults, index=index)

    device_constraints = [
        # d=0  e-heater: heat-node reference device. min=max=0 forces the heat
        #       node to balance at every step (zero-capacity flow node), making
        #       the per-step dispatch deterministic despite flat prices.
        _df(min=0.0, max=0.0, **{"derivative max": 100.0}),
        # d=1  gas boiler: up to 100 kW gas → 100 kW heat (efficiency 1 for clean maths)
        _df(**{"derivative max": 100.0}),
        # d=2  CHP gas input: up to CHP_GAS_MAX kW gas
        _df(**{"derivative max": CHP_GAS_MAX}),
        # d=3  CHP heat output: positive ems_power adds heat to the buffer
        _df(**{"derivative max": CHP_GAS_MAX * ETA_HEAT}),
        # d=4  CHP power output: negative ems_power only (production)
        _df(**{"derivative min": -CHP_GAS_MAX * ETA_POWER, "derivative max": 0.0}),
        # d=5  steam demand: zero flow, constant stock drain of STEAM_DEMAND kW
        _df(**{"stock delta": -STEAM_DEMAND}),
    ]

    ems_constraints = pd.DataFrame(
        {"derivative min": -300.0, "derivative max": 300.0},
        index=index,
    )

    # stock group: all heat-buffer devices share the same stock
    # (key 0 is an arbitrary group id, not a device index)
    heat_group_id = 0
    stock_groups = {heat_group_id: [0, 1, 3, 5]}

    # CHP coupling: gas_in (d=2) is the reference device
    # coeff_heat  = 1/η_heat  = 2.0   → P_heat  = 0.5 * P_gas
    # coeff_power = -1/η_power = -10/3 → P_power = -0.3 * P_gas
    coupling_groups = {
        "chp": [
            (2, 1.0),
            (3, 1.0 / ETA_HEAT),  # = 2.0
            (4, -1.0 / ETA_POWER),  # = -10/3
        ]
    }

    # --- energy-price commitments -------------------------------------------
    # Gas price applies to gas boiler (d=1) and CHP gas input (d=2).
    # Electricity price applies to e-heater (d=0) and CHP power output (d=4).
    # Using both upwards and downwards prices makes each commitment a two-sided
    # soft equality (quantity = 0):
    #   • upward deviation  = consuming more than 0  → positive cost
    #   • downward deviation = producing (negative flow) → negative cost (revenue)
    gas_p = pd.Series(gas_price, index=index)
    elec_p = pd.Series(elec_price, index=index)

    commitments = []
    for d, price in [(1, gas_p), (2, gas_p), (0, elec_p), (4, elec_p)]:
        commitments.append(
            FlowCommitment(
                name="gas cost" if d in (1, 2) else "electricity cost",
                index=index,
                quantity=pd.Series(0.0, index=index),
                upwards_deviation_price=price,
                downwards_deviation_price=price,
                device=pd.Series(d, index=index),
            )
        )

    schedules, _costs, results, _model = device_scheduler(
        device_constraints=device_constraints,
        ems_constraints=ems_constraints,
        commitments=commitments,
        stock_groups=stock_groups,
        coupling_groups=coupling_groups,
    )

    assert results.solver.termination_condition == "optimal", (
        f"Solver did not find an optimal solution "
        f"(gas_price={gas_price}, elec_price={elec_price})"
    )
    return tuple(schedules)


def test_factory_chp_dispatch():
    """Factory: CHP + gas boiler + e-heater competing to meet a fixed steam demand.

    The shared heat buffer (modelled via ``stock_groups``) is drained at a
    constant rate of 15 kW by the steam demand device. Two price scenarios
    verify that the optimizer correctly chooses the cheapest heat source.

    Scenario A — gas cheaper than electricity
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Prices: gas = 20 EUR/kW, electricity = 50 EUR/kW.

    Effective cost per kW of heat delivered:
    - CHP:       gas_cost − power_revenue  = (20·20 − 50·6) / 10 = 10 EUR/kW
    - gas boiler: 20 EUR/kW  (efficiency = 1)
    - e-heater:   50 EUR/kW

    Merit order: CHP ≪ gas boiler ≪ e-heater.

    With CHP at maximum (20 kW gas → 10 kW heat + 6 kW power):
    - remaining heat demand = 15 − 10 = 5 kW → gas boiler
    - e-heater not needed

    Scenario B — electricity cheaper than gas
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Prices: gas = 100 EUR/kW, electricity = 10 EUR/kW.

    Effective cost per kW of heat:
    - CHP:       (100·20 − 10·6) / 10 = 194 EUR/kW
    - gas boiler: 100 EUR/kW
    - e-heater:   10 EUR/kW

    Merit order: e-heater ≪ gas boiler ≪ CHP.

    All 15 kW steam demand is met by the e-heater; CHP and gas boiler are off.
    """
    # ------------------------------------------------------------------ #
    # Scenario A: gas cheaper — CHP at max, gas boiler fills the rest      #
    # ------------------------------------------------------------------ #
    (e_heater, gas_boiler, chp_gas, chp_heat, chp_power, _demand) = (
        _run_factory_scenario(gas_price=20.0, elec_price=50.0)
    )

    expected_chp_gas = pd.Series(20.0, index=e_heater.index)
    expected_chp_heat = pd.Series(10.0, index=e_heater.index)  # 0.5 * 20
    expected_chp_power = pd.Series(-6.0, index=e_heater.index)  # -0.3 * 20
    expected_boiler = pd.Series(5.0, index=e_heater.index)  # fills 15-10 kW gap
    expected_eheater = pd.Series(0.0, index=e_heater.index)

    pd.testing.assert_series_equal(
        chp_gas,
        expected_chp_gas,
        check_names=False,
        rtol=1e-4,
        obj="Scenario A: CHP gas input at maximum (20 kW)",
    )
    pd.testing.assert_series_equal(
        chp_heat,
        expected_chp_heat,
        check_names=False,
        rtol=1e-4,
        obj="Scenario A: CHP heat output = 0.5 × gas input (10 kW)",
    )
    pd.testing.assert_series_equal(
        chp_power,
        expected_chp_power,
        check_names=False,
        rtol=1e-4,
        obj="Scenario A: CHP power output = −0.3 × gas input (−6 kW)",
    )
    pd.testing.assert_series_equal(
        gas_boiler,
        expected_boiler,
        check_names=False,
        rtol=1e-4,
        obj="Scenario A: gas boiler fills remaining 5 kW heat demand",
    )
    pd.testing.assert_series_equal(
        e_heater,
        expected_eheater,
        check_names=False,
        atol=1e-4,
        obj="Scenario A: e-heater not used (gas is cheapest)",
    )

    # ------------------------------------------------------------------ #
    # Scenario B: electricity cheaper — e-heater meets all demand          #
    # ------------------------------------------------------------------ #
    (e_heater, gas_boiler, chp_gas, chp_heat, chp_power, _demand) = (
        _run_factory_scenario(gas_price=100.0, elec_price=10.0)
    )

    expected_eheater_b = pd.Series(15.0, index=e_heater.index)
    expected_zero = pd.Series(0.0, index=e_heater.index)

    pd.testing.assert_series_equal(
        e_heater,
        expected_eheater_b,
        check_names=False,
        rtol=1e-4,
        obj="Scenario B: e-heater meets all 15 kW steam demand",
    )
    pd.testing.assert_series_equal(
        chp_gas,
        expected_zero,
        check_names=False,
        atol=1e-4,
        obj="Scenario B: CHP not used (electricity is cheapest)",
    )
    pd.testing.assert_series_equal(
        gas_boiler,
        expected_zero,
        check_names=False,
        atol=1e-4,
        obj="Scenario B: gas boiler not used (electricity is cheapest)",
    )
