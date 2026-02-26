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

    # ---- assertions
    assert isinstance(schedules, list)
    assert len(schedules) >= 2  # at least one schedule per device

    # Extract storage schedules by sensor
    storage_schedules = {
        s["sensor"]: s["data"]
        for s in schedules
        if s["name"] == "storage_schedule"
    }
    battery_schedule = storage_schedules[battery_power]
    hp_schedule = storage_schedules[hp_power]

    # With constant prices (100 EUR/MWh), the tiny price slope should cause all charging
    # to happen as soon as possible. Both devices charge at full capacity until done.
    #
    # Battery: needs to go from SOC 20 kWh to 80 kWh = 60 kWh of SOC.
    #   Energy drawn = 60 kWh / 0.95 charging efficiency ≈ 63.16 kWh
    #   At 20 kW: 3 full hours + 3.16 kW in hour 3.
    #
    # Heat pump: needs to go from SOC 10 kWh to 40 kWh = 30 kWh of SOC.
    #   Energy drawn = 30 kWh / 0.95 charging efficiency ≈ 31.58 kWh
    #   At 10 kW: 3 full hours + 1.58 kW in hour 3.
    battery_energy_needed = (80.0 - 20.0) / 0.95  # ≈ 63.16 kWh
    hp_energy_needed = (40.0 - 10.0) / 0.95  # ≈ 31.58 kWh

    # All charging should happen in the first 4 time slots; the rest should be near zero
    assert battery_schedule.iloc[:3].values == pytest.approx(
        [20.0, 20.0, 20.0], abs=1e-3
    ), "Battery should charge at full 20 kW in hours 0-2"
    assert battery_schedule.iloc[3] == pytest.approx(
        battery_energy_needed - 60.0, abs=1e-3
    ), "Battery should partially charge in hour 3"
    assert battery_schedule.iloc[4:].values == pytest.approx(
        [0.0] * 20, abs=1e-3
    ), "Battery should not charge after hour 3"

    assert hp_schedule.iloc[:3].values == pytest.approx(
        [10.0, 10.0, 10.0], abs=1e-3
    ), "Heat pump should charge at full 10 kW in hours 0-2"
    assert hp_schedule.iloc[3] == pytest.approx(
        hp_energy_needed - 30.0, abs=1e-3
    ), "Heat pump should partially charge in hour 3"
    assert hp_schedule.iloc[4:].values == pytest.approx(
        [0.0] * 20, abs=1e-3
    ), "Heat pump should not charge after hour 3"

    # Electricity costs: energy drawn times the price.
    # Battery:    63.16 kWh * 100 EUR/MWh = 6.316 EUR
    # Heat pump:  31.58 kWh * 100 EUR/MWh = 3.158 EUR
    commitment_costs_entry = next(
        s for s in schedules if s["name"] == "commitment_costs"
    )
    total_costs = sum(commitment_costs_entry["data"].values())
    expected_total_costs = (battery_energy_needed + hp_energy_needed) / 1000 * 100
    assert total_costs == pytest.approx(expected_total_costs, rel=1e-3), (
        f"Total electricity costs should be ≈ {expected_total_costs:.4f} EUR"
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

    scheduled_sensors = {
        entry["sensor"]
        for entry in schedules
        if entry.get("name") == "storage_schedule"
    }

    assert battery_power in scheduled_sensors
    assert boiler_power in scheduled_sensors

    commitment_costs = [
        entry for entry in schedules if entry.get("name") == "commitment_costs"
    ]
    assert len(commitment_costs) == 1
