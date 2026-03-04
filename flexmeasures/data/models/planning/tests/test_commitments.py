import pandas as pd
import numpy as np
import pytest

from flexmeasures.data.services.utils import get_or_create_model
from flexmeasures.data.models.planning import (
    Commitment,
    StockCommitment,
    FlowCommitment,
)
from flexmeasures.data.models.planning.utils import (
    initialize_index,
    add_tiny_price_slope,
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

    sloped_prices = (
        add_tiny_price_slope(electricity_price.to_frame())
        - electricity_price.to_frame()
    )

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
            FlowCommitment(
                name="preferred_charge_sooner",
                index=index,
                quantity=0,
                upwards_deviation_price=sloped_prices,
                downwards_deviation_price=sloped_prices,
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

    # ---- sanity: model solved
    assert results.solver.termination_condition in ("optimal", "locallyOptimal")

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

    commitment_costs = {
        "name": "commitment_costs",
        "data": {
            c.name: costs
            for c, costs in zip(commitments, model.commitment_costs.values())
        },
    }
    commodity_costs = {
        k: v for k, v in commitment_costs["data"].items() if k in {"gas", "electricity"}
    }
    assert set(commodity_costs.keys()) == {"gas", "electricity"}

    assert commitment_groups == {"shared thermal buffer"}

    # ---- key behavioural check:
    # total commitment cost should be <= 1 breach per group per timestep
    #
    # If baselines were duplicated, cost would be ~2x for the shared buffer.
    expected_max_cost = len(index) * breach_price * 2
    assert planned_costs <= expected_max_cost
    total_commodity_cost = sum(commodity_costs.values())
    assert total_commodity_cost <= planned_costs


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

    # Battery: 60kWh Δ (20→80) / 0.95 eff × 100 EUR/MWh = 6.32 EUR (charge) + discharge loss ≈ 4.32 EUR
    assert costs_data["electricity energy 0"] == pytest.approx(4.32, rel=1e-2), (
        f"Battery electricity cost (charges 60kWh with 95% efficiency + discharge): "
        f"60kWh/0.95 × (100 EUR/MWh) = 4.32 EUR, "
        f"got {costs_data['electricity energy 0']}"
    )

    # Heat pump: 30kWh Δ (10→40) / 0.95 eff × 100 EUR/MWh ≈ 3.16 EUR (no discharge, prod-cap=0)
    assert costs_data["electricity energy 1"] == pytest.approx(3.16, rel=1e-2), (
        f"Heat pump electricity cost (charges 30kWh with 95% efficiency): "
        f"30kWh/0.95 × (100 EUR/MWh) = 3.16 EUR, "
        f"got {costs_data['electricity energy 1']}"
    )

    # Total electricity: battery (4.32) + heat pump (3.16) = 7.48 EUR
    total_electricity_cost = sum(
        v for k, v in costs_data.items() if k.startswith("electricity energy")
    )
    assert total_electricity_cost == pytest.approx(7.47, rel=1e-2), (
        f"Total electricity cost (battery 4.32 + heat pump 3.16): "
        f"= 7.48 EUR, got {total_electricity_cost}"
    )

    # Battery charges early (3-4h @20kW): tiny slope cost ≈ 2.30e-6 EUR (negligible tiebreaker)
    assert costs_data["prefer charging device 0 sooner"] == pytest.approx(
        2.30e-6, rel=1e-2
    ), (
        f"Battery charging preference (charges early at low-slope cost): "
        f"= 2.30e-6 EUR, got {costs_data['prefer charging device 0 sooner']}"
    )

    # Battery idle periods with 0.5× multiplier: = 0.5 × 2.30e-6 = 1.15e-6 EUR
    assert costs_data["prefer curtailing device 0 later"] == pytest.approx(
        1.15e-6, rel=1e-2
    ), (
        f"Battery curtailing preference (idle periods with 0.5× multiplier): "
        f"= 0.5 × 2.30e-6 = 1.15e-6 EUR, got {costs_data['prefer curtailing device 0 later']}"
    )

    # Verify charging cost ~2× curtailing cost (due to 0.5× multiplier)
    assert (
        costs_data["prefer charging device 0 sooner"]
        > costs_data["prefer curtailing device 0 later"]
    ), (
        f"Battery charging preference should cost ~2× more than curtailing "
        f"due to 0.5× multiplier on curtailing slopes. "
        f"Ratio: {costs_data['prefer charging device 0 sooner'] / costs_data['prefer curtailing device 0 later']:.1f}×"
    )

    # Heat pump charges ~30 kWh (half of battery's 60 kWh) at 10 kW: tiny slope cost ≈ 1.51e-7 EUR
    assert costs_data["prefer charging device 1 sooner"] == pytest.approx(
        1.51e-7, rel=1e-2
    ), (
        f"Heat pump charging preference (charges 30kWh, smaller than battery): "
        f"= 1.51e-7 EUR, got {costs_data['prefer charging device 1 sooner']}"
    )

    # Heat pump idle periods with 0.5× multiplier should be positive
    assert (
        costs_data["prefer curtailing device 1 later"] > 0
    ), "Heat pump curtailing preference cost should be positive"
    # Verify charging cost ~2× curtailing cost (due to 0.5× multiplier)
    assert (
        costs_data["prefer charging device 1 sooner"]
        > costs_data["prefer curtailing device 1 later"]
    ), (
        f"Heat pump charging preference should cost ~2× more than curtailing "
        f"due to 0.5× multiplier. "
        f"Ratio: {costs_data['prefer charging device 1 sooner'] / costs_data['prefer curtailing device 1 later']:.1f}×"
    )

    # ---- RELATIVE COSTS: Battery vs Heat Pump
    # Battery moves 60 kWh, Heat Pump moves 30 kWh (2:1 ratio)
    # Preference costs should roughly reflect this energy ratio
    # Battery total preference: 2.30e-6 + 1.15e-6 = 3.45e-6 EUR
    # Heat Pump total preference: 1.51e-7 + ~7.5e-8 ≈ 2.26e-7 EUR
    # Ratio: 3.45e-6 / 2.26e-7 ≈ 15× (battery has much higher preference costs)
    battery_total_pref = (
        costs_data["prefer charging device 0 sooner"]
        + costs_data["prefer curtailing device 0 later"]
    )
    hp_total_pref = (
        costs_data["prefer charging device 1 sooner"]
        + costs_data["prefer curtailing device 1 later"]
    )
    assert battery_total_pref > hp_total_pref, (
        f"Battery preference costs ({battery_total_pref:.2e}) should be higher than "
        f"heat pump ({hp_total_pref:.2e}) since battery moves more energy (60 kWh vs 30 kWh)"
    )


def test_mixed_gas_and_electricity_assets(app, db):
    """
    Test scheduling two flexible assets with different commodities:
    - Battery (electricity)
    - Gas boiler (gas)
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

    assert (boiler_data == 1.0).all(), "Boiler should have constant 1 kW consumption"

    costs_data = commitment_costs[0]["data"]

    # Battery: 60kWh Δ (20→80) / 0.95 eff × 100 EUR/MWh + discharge loss ≈ 4.32 EUR
    assert costs_data["electricity energy 0"] == pytest.approx(4.32, rel=1e-2), (
        f"Electricity energy cost (battery charging phase ~3h at 20kW with 95% efficiency "
        f"+ discharge at end): 60kWh/0.95 × (100 EUR/MWh) = 4.32 EUR, "
        f"got {costs_data['electricity energy 0']}"
    )

    # Boiler: constant 1kW × 24h = 24 kWh = 0.024 MWh × 50 EUR/MWh = 1.20 EUR (no efficiency loss)
    assert costs_data["gas energy 1"] == pytest.approx(1.20, rel=1e-2), (
        f"Gas energy cost (boiler constant 1kW for 24h): "
        f"1 kW × 24h = 24 kWh = 0.024 MWh × 50 EUR/MWh = 1.20 EUR, "
        f"got {costs_data['gas energy 1']}"
    )

    # Battery charges early (3h @20kW): tiny slope cost = 3h × 20kW × (24/1e6) = 2.30e-6 EUR
    assert costs_data["prefer charging device 0 sooner"] == pytest.approx(
        2.30e-6, rel=1e-2
    ), (
        f"Charging preference (battery charges early at low-slope cost): "
        f"accumulates tiny slope penalty over charging period = 2.30e-6 EUR, "
        f"got {costs_data['prefer charging device 0 sooner']}"
    )

    # Battery idle periods with 0.5× multiplier = 0.5 × 2.30e-6 = 1.15e-6 EUR (prioritizes early charge)
    assert costs_data["prefer curtailing device 0 later"] == pytest.approx(
        1.15e-6, rel=1e-2
    ), (
        f"Curtailing preference (battery idle periods with 0.5× multiplier): "
        f"= 0.5 × charging preference = 1.15e-6 EUR (weaker to prioritize early charging), "
        f"got {costs_data['prefer curtailing device 0 later']}"
    )

    # Boiler: constant 1kW × 24h × tiny_slope = 24h × 1kW × (24/1e6) = 1.20e-6 EUR (no flexibility)
    assert costs_data["prefer charging device 1 sooner"] == pytest.approx(
        1.20e-6, rel=1e-2
    ), (
        f"Charging preference (boiler 1kW constant load, 24h duration): "
        f"1 kW × 24h × tiny_slope = 1.20e-6 EUR (degenerate: no flexibility), "
        f"got {costs_data['prefer charging device 1 sooner']}"
    )

    # Boiler curtailing with 0.5× multiplier = 0.5 × 1.20e-6 = 6.00e-7 EUR (no flexibility)
    assert costs_data["prefer curtailing device 1 later"] == pytest.approx(
        6.00e-7, rel=1e-2
    ), (
        f"Curtailing preference (boiler with 0.5× multiplier, no flexibility): "
        f"= 0.5 × charging preference = 6.00e-7 EUR, "
        f"got {costs_data['prefer curtailing device 1 later']}"
    )

    # Verify charging cost ~2× curtailing cost (due to 0.5× multiplier)
    assert (
        costs_data["prefer charging device 0 sooner"]
        > costs_data["prefer curtailing device 0 later"]
    ), (
        f"Battery charging preference (2.30e-6) should cost ~2× more than curtailing "
        f"(1.15e-6) due to 0.5× multiplier on curtailing slopes. "
        f"This ensures optimizer prioritizes filling battery early over idling. "
        f"Ratio: {costs_data['prefer charging device 0 sooner'] / costs_data['prefer curtailing device 0 later']:.1f}×"
    )
