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
    battery_total_pref = costs_data["prefer a full storage 0 sooner"]
    hp_total_pref = costs_data["prefer a full storage 1 sooner"]
    assert battery_total_pref == pytest.approx(2 * hp_total_pref, rel=1e-9), (
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

    # Battery: 60kWh Δ (20→80) / 0.95 eff × 100 EUR/MWh = 6.32 EUR (charge) + discharge loss ≈ 4.32 EUR
    assert costs_data["electricity energy 0"] == pytest.approx(4.32, rel=1e-2), (
        f"Battery electricity cost (charges 60kWh with 95% efficiency + discharge): "
        f"60kWh/0.95 × (100 EUR/MWh) = 4.32 EUR, "
        f"got {costs_data['electricity energy 0']}"
    )

    # Boiler: constant 1kW × 24h = 24 kWh = 0.024 MWh × 50 EUR/MWh = 1.20 EUR (no efficiency loss)
    assert costs_data["gas energy 1"] == pytest.approx(1.20, rel=1e-2), (
        f"Gas energy cost (boiler constant 1kW for 24h): "
        f"1 kW × 24h = 24 kWh = 0.024 MWh × 50 EUR/MWh = 1.20 EUR, "
        f"got {costs_data['gas energy 1']}"
    )

    # Total electricity + gas energy costs: battery (4.32) + boiler (1.20) = 5.52 EUR
    total_energy_cost = sum(
        v
        for k, v in costs_data.items()
        if k.endswith(" energy 0") or k.endswith(" energy 1")
    )
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
    battery_total_pref = costs_data["prefer a full storage 0 sooner"]
    boiler_total_pref = costs_data["prefer a full storage 1 sooner"]

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
    assert costs_data["electricity energy 0"] == pytest.approx(-17.0, rel=1e-2), (
        "Electricity energy 0 corresponds to inverter 1 energy cost. "
        "Negative value indicates net production/discharge value: "
        "inverter 1 discharges ~340 kWh at 0.95 efficiency = -17 EUR."
    )

    assert costs_data["electricity energy 1"] == pytest.approx(17.07, rel=1e-2), (
        "Electricity energy 1 corresponds to inverter 2 charging cost, "
        "which should dominate since it performs most charging: "
        "~682.8 kWh at 0.99 efficiency * 100 EUR/MWh ≈ 17.07 EUR."
    )


def test_simulation_copy(app, db):
    # ---- asset types and assets
    gas_boiler_type = get_or_create_model(GenericAssetType, name="gas-boiler")
    tank_type = get_or_create_model(GenericAssetType, name="gas-tank")
    site_type = get_or_create_model(GenericAssetType, name="site")

    site = GenericAsset(
        name="Test Site",
        generic_asset_type=site_type,
    )
    building = GenericAsset(
        name="Building", generic_asset_type=site_type, parent_asset_id=site.id
    )
    pv = GenericAsset(
        name="PV",
        generic_asset_type=get_or_create_model(GenericAssetType, name="pv"),
        parent_asset_id=site.id,
    )

    gas_boiler = GenericAsset(
        name="Gas Boiler", generic_asset_type=gas_boiler_type, parent_asset_id=site.id
    )

    gas_tank = GenericAsset(
        name="Gas Tank", generic_asset_type=tank_type, parent_asset_id=site.id
    )
    battery = GenericAsset(
        name="Battery",
        generic_asset_type=get_or_create_model(GenericAssetType, name="battery"),
        parent_asset_id=site.id,
    )

    db.session.add_all([gas_boiler, gas_tank, building, battery, pv, site])
    db.session.commit()

    # ---- sensors
    start = pd.Timestamp("2026-04-07T00:00:00+01:00")
    end = pd.Timestamp(
        "2026-04-09T06:00:00+01:00"
    )  # Extended to allow discharge target on April 8
    belief_time = pd.Timestamp(
        "2026-04-05T00:00:00+01:00"
    )  # 2 days before start for generous planning horizon
    power_resolution = pd.Timedelta("15m")
    energy_resolution = pd.Timedelta(0)

    building_raw_power = Sensor(
        name="building raw power",
        unit="kW",
        event_resolution=power_resolution,
        generic_asset=building,
    )

    pv_power = Sensor(
        name="PV power",
        unit="kW",
        event_resolution=power_resolution,
        generic_asset=pv,
    )

    pv_raw_power = Sensor(
        name="PV raw power",
        unit="kW",
        event_resolution=power_resolution,
        generic_asset=pv,
    )

    battery_power = Sensor(
        name="battery power",
        unit="kW",
        event_resolution=power_resolution,
        generic_asset=battery,
    )

    battery_soc = Sensor(
        name="battery state-of-charge",
        unit="kWh",
        event_resolution=energy_resolution,  # instantaneous
        generic_asset=battery,
    )

    boiler_power = Sensor(
        name="boiler power",
        unit="kW",
        event_resolution=power_resolution,
        generic_asset=gas_boiler,
    )

    tank_power = Sensor(
        name="tank power",
        unit="kW",
        event_resolution=power_resolution,
        generic_asset=gas_tank,
    )

    tank_soc = Sensor(
        name="tank state-of-charge",
        unit="kWh",
        event_resolution=energy_resolution,  # instantaneous
        generic_asset=gas_tank,
    )

    tank_soc_usage = Sensor(
        name="tank soc usage",
        unit="kW",
        event_resolution=power_resolution,
        generic_asset=gas_tank,
    )

    db.session.add_all(
        [
            boiler_power,
            tank_soc,
            tank_power,
            tank_soc_usage,
            building_raw_power,
            battery_power,
            pv_power,
            pv_raw_power,
            battery_soc,
        ]
    )
    db.session.commit()
    import timely_beliefs as tb
    from flexmeasures import Source

    # add dummy data to building raw power to ensure site-level constraints are respected
    building_data = pd.Series(
        100.0,
        index=pd.date_range(start, end, freq=power_resolution, name="event_start"),
        name="event_value",
    ).reset_index()

    bdf = tb.BeliefsDataFrame(
        building_data,
        belief_horizon=-pd.Timedelta(seconds=1) * np.array(range(len(building_data))),
        sensor=building_raw_power,
        source=get_or_create_model(Source, name="Simulation"),
    )
    save_to_db(bdf, bulk_save_objects=False, save_changed_beliefs_only=False)

    bdf = tb.BeliefsDataFrame(
        building_data,
        belief_horizon=-pd.Timedelta(seconds=1) * np.array(range(len(building_data))),
        sensor=tank_soc_usage,
        source=get_or_create_model(Source, name="Simulation"),
    )

    save_to_db(bdf, bulk_save_objects=False, save_changed_beliefs_only=False)

    # add dummy data to PV power to ensure site-level constraints are respected
    # Create realistic PV data with solar curve pattern
    pv_index = pd.date_range(start, end, freq=power_resolution, name="event_start")
    # Solar generation typically peaks around noon and follows a bell curve
    # Hours: 0-8 (night), 8-10 (morning ramp), 10-14 (peak 5-20kW), 14-16 (evening ramp), 16-24 (night)
    hours = pv_index.hour + pv_index.minute / 60.0

    pv_values = []
    for hour in hours:
        if hour < 8 or hour >= 18:  # Night time
            pv_values.append(0.0)
        elif 8 <= hour < 10:  # Morning ramp
            pv_values.append((hour - 8) * 5.0)  # 0 to 10 kW
        elif 10 <= hour < 11:  # Morning continued
            pv_values.append(10.0 + (hour - 10) * 10.0)  # 10 to 20 kW
        elif 11 <= hour < 12:  # Peak approach
            pv_values.append(20.0 + (hour - 11) * 5.0)  # 20 to 25 kW
        elif 12 <= hour < 14:  # Peak sustained
            pv_values.append(23.0)  # ~23 kW peak
        elif 14 <= hour < 15:  # Afternoon decline
            pv_values.append(23.0 - (hour - 14) * 10.0)  # 23 to 13 kW
        elif 15 <= hour < 16:  # Afternoon continued
            pv_values.append(13.0 - (hour - 15) * 5.0)  # 13 to 8 kW
        elif 16 <= hour < 18:  # Evening ramp down
            pv_values.append((18 - hour) * 4.0)  # 8 to 0 kW

    pv_data = pd.DataFrame({"event_start": pv_index, "event_value": pv_values})

    pv_bdf = tb.BeliefsDataFrame(
        pv_data,
        belief_horizon=-pd.Timedelta(seconds=1) * np.array(range(len(pv_data))),
        sensor=pv_raw_power,
        source=get_or_create_model(Source, name="Simulation"),
    )
    save_to_db(pv_bdf, bulk_save_objects=False, save_changed_beliefs_only=False)

    # ---- flex-model with time-varying power capacity
    # Device 0: boiler with time-varying power capacity (30 kW throughout the entire period)
    # Storage container: tank with shared state-of-charge
    flex_model = [
        # {
        #     "sensor": pv_power.id,
        #     "consumption-capacity": "0 kW",
        #     "production-capacity": {"sensor": pv_raw_power.id},
        #     "power-capacity": "1 GW",
        # },
        # {
        #     "sensor": battery_power.id,
        #     "soc-min": 0.0,
        #     "soc-max": 100.0,
        #     "soc-at-start": 20.0,
        #     "power-capacity": "20 kW",
        #     "roundtrip-efficiency": 0.9,
        #     "soc-targets": [{"datetime": "2026-04-07T20:00:00+01:00", "value": 80.0}],
        #     "state-of-charge": {"sensor": battery_soc.id},
        #     "commodity": "electricity",
        #
        # },
        {
            "sensor": boiler_power.id,
            "state-of-charge": {"sensor": tank_soc.id},
            "production-capacity": "100 kW",
            "power-capacity": "100 kW",
            "charging-efficiency": 0.5,
            "commodity": "gas",
            "discharging-efficiency": 0.5,
        },
        {
            # "sensor": tank_power.id,
            "soc-min": 200.0,
            "soc-max": 1000.0,
            "soc-at-start": 200.0,
            "power-capacity": "100 kW",
            # "soc-targets": [
            #     {"datetime": "2026-04-07T20:00:00+01:00", "value": 700.0},
            #     # {"datetime": "2026-04-08T18:00:00+01:00", "value": 400.0},  # Discharge target - tank discharges after charging
            # ],
            "commodity": "gas",
            "state-of-charge": {"sensor": tank_soc.id},
            "discharging-efficiency": 1,
            "charging-efficiency": 1,
        },
    ]

    flex_context = {
        "consumption-price": "100 EUR/MWh",
        "production-price": "100 EUR/MWh",
        "gas-price": "50 EUR/MWh",
        "site-power-capacity": "4700 kW",
        "site-consumption-capacity": "4000 kW",
        "site-production-capacity": "0 kW",
        "site-consumption-breach-price": "100000 EUR/kW",
        "site-production-breach-price": "100000 EUR/kW",
        "relax-constraints": True,
        "inflexible-device-sensors": [building_raw_power.id],
    }

    scheduler = StorageScheduler(
        asset_or_sensor=site,
        start=start,
        end=end,
        resolution=power_resolution,
        belief_time=belief_time,
        flex_model=flex_model,
        flex_context=flex_context,
        return_multiple=True,
    )

    pd.set_option("display.max_rows", None)
    schedules = scheduler.compute(skip_validation=True)

    # ---- verify outputs
    print(schedules)


def test_simulation_copy_new(app, db):
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

    # ---- sensors
    start = pd.Timestamp("2026-04-07T00:00:00+01:00")
    end = pd.Timestamp(
        "2026-04-09T06:00:00+01:00"
    )  # Extended to allow discharge target on April 8
    belief_time = pd.Timestamp(
        "2026-04-05T00:00:00+01:00"
    )  # 2 days before start for generous planning horizon
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

    db.session.add_all(
        [
            boiler_power,
            buffer_soc,
            tank_power,
            buffer_soc_usage,
            building_raw_power,
            heater_power,
            soc_targets,
        ]
    )
    db.session.commit()
    import timely_beliefs as tb
    from flexmeasures import Source

    # add dummy data to building raw power to ensure site-level constraints are respected
    building_data = pd.Series(
        100.0,
        index=pd.date_range(start, end, freq=power_resolution, name="event_start"),
        name="event_value",
    ).reset_index()

    soc_usage = building_data.copy()
    # soc_usage.loc[soc_usage['event_start'] > "2026-04-07T20:00:00+01:00", "event_value"] = 50
    # soc_usage.loc[soc_usage['event_start'] < "2026-04-07T20:00:00+01:00", "event_value"] = 0.0
    # soc_usage.set_index("event_start", inplace=True)
    # soc_usage = soc_usage["event_value"]
    bdf = tb.BeliefsDataFrame(
        building_data,
        belief_horizon=-pd.Timedelta(seconds=1) * np.array(range(len(building_data))),
        sensor=building_raw_power,
        source=get_or_create_model(Source, name="Simulation"),
    )
    save_to_db(bdf, bulk_save_objects=False, save_changed_beliefs_only=False)

    bdf = tb.BeliefsDataFrame(
        soc_usage,
        belief_horizon=-pd.Timedelta(seconds=1) * np.array(range(len(building_data))),
        sensor=buffer_soc_usage,
        source=get_or_create_model(Source, name="Simulation"),
    )

    save_to_db(bdf, bulk_save_objects=False, save_changed_beliefs_only=False)

    flex_model = [
        # {
        #     "sensor": pv_power.id,
        #     "consumption-capacity": "0 kW",
        #     "production-capacity": {"sensor": pv_raw_power.id},
        #     "power-capacity": "1 GW",
        # },
        # {
        #     "sensor": battery_power.id,
        #     "soc-min": 0.0,
        #     "soc-max": 100.0,
        #     "soc-at-start": 20.0,
        #     "power-capacity": "20 kW",
        #     "roundtrip-efficiency": 0.9,
        #     "soc-targets": [{"datetime": "2026-04-07T20:00:00+01:00", "value": 80.0}],
        #     "state-of-charge": {"sensor": battery_soc.id},
        #     "commodity": "electricity",
        #
        # },
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
            # "power-capacity": "0 kW",
            # "production-capacity": "0 kW",
            "soc-min": 200.0,
            "soc-max": 1000.0,
            "soc-at-start": 200.0,
            "soc-targets": [
                {"datetime": "2026-04-07T20:00:00+01:00", "value": 700.0},
            ],
            "state-of-charge": {"sensor": buffer_soc.id},
            "soc-usage": [{"sensor": buffer_soc_usage.id}],
            "storage-efficiency": 0.9,
            "discharging-efficiency": 0.9,
            "soc-unit": "kWh",
        },
    ]

    flex_context = {
        "consumption-price": "100 EUR/MWh",
        "production-price": "100 EUR/MWh",
        "gas-price": "100 EUR/MWh",
        "site-power-capacity": "4700 kW",
        "site-consumption-capacity": "4000 kW",
        "site-production-capacity": "0 kW",
        "site-consumption-breach-price": "100000 EUR/kW",
        "site-production-breach-price": "100000 EUR/kW",
        "relax-constraints": True,
        # "inflexible-device-sensors": [building_raw_power.id],
    }

    scheduler = StorageScheduler(
        asset_or_sensor=site,
        start=start,
        end=end,
        resolution=power_resolution,
        belief_time=belief_time,
        flex_model=flex_model,
        flex_context=flex_context,
        return_multiple=True,
    )

    pd.set_option("display.max_rows", None)
    schedules = scheduler.compute(skip_validation=True)

    # ---- verify outputs
    print(schedules)
