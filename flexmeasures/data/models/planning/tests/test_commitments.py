import pytest
import pandas as pd
import numpy as np

from flexmeasures.data.models.planning import (
    Commitment,
    StockCommitment,
    FlowCommitment,
)
from flexmeasures.data.models.planning.utils import (
    initialize_index,
)
from flexmeasures.data.models.planning.linear_optimization import device_scheduler


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

    # The shared buffer minimum (SoC ≥ 100 at the final step) must be met without
    # any breach.  If baseline costs were duplicated the optimiser would be driven
    # to over-invest in commodities to avoid inflated penalties, which would also
    # show up here as a non-zero breach cost.
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
