import uuid
from datetime import timedelta

import pytest
import pandas as pd

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.utils.unit_utils import ur


def _unique_name(prefix: str) -> str:
    return f"{prefix} {uuid.uuid4().hex[:8]}"


def make_sensors(db, building, n=2, unit="MW"):
    sensors = []
    for i in range(n):
        s = Sensor(
            name=_unique_name(f"group test power sensor {i}"),
            generic_asset=building,
            event_resolution=timedelta(hours=1),
            unit=unit,
        )
        db.session.add(s)
        sensors.append(s)
    db.session.commit()
    return sensors


def make_group_sensor(db, building, unit="MW"):
    s = Sensor(
        name=_unique_name("group aggregate sensor"),
        generic_asset=building,
        event_resolution=timedelta(hours=1),
        unit=unit,
    )
    db.session.add(s)
    db.session.commit()
    return s


def base_flex_context():
    return {
        "consumption_price": ur.Quantity("100 EUR/MWh"),
        "production_price": ur.Quantity("100 EUR/MWh"),
        "shared_currency_unit": "EUR",
    }


def run_scheduler(building, flex_model, flex_context, **kwargs):
    start = pd.Timestamp("2023-01-01T00:00:00", tz="Europe/Amsterdam")
    end = start + timedelta(hours=4)
    resolution = timedelta(hours=1)
    scheduler = StorageScheduler(
        asset_or_sensor=building,
        start=start,
        end=end,
        resolution=resolution,
        flex_model=flex_model,
        flex_context=flex_context,
        **kwargs,
    )
    scheduler.config_deserialized = True
    return scheduler


def test_group_hard_power_capacity_caps_aggregate(db, building):
    """Inverter-like case (#2092): battery + PV producer under a group with a tight
    power-capacity should cap the *sum* of their schedules, even though each device
    individually would want to go to its own max."""
    battery, pv = make_sensors(db, building, n=2)
    group_sensor = make_group_sensor(db, building)

    flex_model = [
        {
            "sensor": battery,
            "soc_at_start": 1.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "consumption_capacity": ur.Quantity("2 MW"),
            "production_capacity": ur.Quantity("2 MW"),
            "group": {"sensor": group_sensor},
        },
        {
            "sensor": pv,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "consumption_capacity": ur.Quantity("0 MW"),
            "production_capacity": ur.Quantity("2 MW"),
            "group": {"sensor": group_sensor},
        },
        {
            "sensor": group_sensor,
            "power_capacity_in_mw": ur.Quantity("2.5 MW"),
        },
    ]
    scheduler = run_scheduler(
        building, flex_model, base_flex_context(), return_multiple=True
    )
    results = scheduler.compute()

    schedules = {
        r["sensor"]: r["data"] for r in results if r.get("name") == "storage_schedule"
    }
    assert battery in schedules
    assert pv in schedules
    assert group_sensor in schedules

    aggregate = schedules[group_sensor]
    assert (aggregate.abs() <= 2.5 + 1e-6).all()
    # the group's aggregate should equal the sum of its members
    assert ((schedules[battery] + schedules[pv] - aggregate).abs() < 1e-6).all()


def test_group_absent_allows_larger_aggregate(db, building):
    """Control run: without the group constraint, the same devices are not capped."""
    battery, pv = make_sensors(db, building, n=2)

    flex_model = [
        {
            "sensor": battery,
            "soc_at_start": 1.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "consumption_capacity": ur.Quantity("2 MW"),
            "production_capacity": ur.Quantity("2 MW"),
        },
        {
            "sensor": pv,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "consumption_capacity": ur.Quantity("0 MW"),
            "production_capacity": ur.Quantity("2 MW"),
        },
    ]
    scheduler = run_scheduler(
        building, flex_model, base_flex_context(), return_multiple=True
    )
    results = scheduler.compute()
    schedules = {
        r["sensor"]: r["data"] for r in results if r.get("name") == "storage_schedule"
    }
    combined_abs_max = (schedules[battery] + schedules[pv]).abs().max()
    assert combined_abs_max > 2.5


def test_group_soft_directional_capacity(db, building):
    """A tight consumption-capacity on the group is soft (breach commitments), but the
    hard power-capacity remains a true cap."""
    battery, pv = make_sensors(db, building, n=2)
    group_sensor = make_group_sensor(db, building)

    flex_model = [
        {
            "sensor": battery,
            "soc_at_start": 1.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "consumption_capacity": ur.Quantity("2 MW"),
            "production_capacity": ur.Quantity("2 MW"),
            "group": {"sensor": group_sensor},
        },
        {
            "sensor": pv,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "consumption_capacity": ur.Quantity("0 MW"),
            "production_capacity": ur.Quantity("2 MW"),
            "group": {"sensor": group_sensor},
        },
        {
            "sensor": group_sensor,
            "power_capacity_in_mw": ur.Quantity("2.5 MW"),
            "consumption_capacity": ur.Quantity("1 MW"),
        },
    ]
    scheduler = run_scheduler(
        building, flex_model, base_flex_context(), return_multiple=True
    )
    results = scheduler.compute()

    schedules = {
        r["sensor"]: r["data"] for r in results if r.get("name") == "storage_schedule"
    }
    aggregate = schedules[group_sensor]
    # With default (very high) breach prices and moderate test prices, breaching
    # should never be worthwhile: the soft directional bound behaves like a cap.
    assert (aggregate <= 1 + 1e-6).all()
    # Hard power-capacity remains a hard cap regardless.
    assert (aggregate.abs() <= 2.5 + 1e-6).all()

    commitment_costs = next(
        r["data"] for r in results if r.get("name") == "commitment_costs"
    )
    assert any(
        "group" in name and "consumption breach" in name for name in commitment_costs
    )


def test_group_dangling_reference_raises(db, building):
    battery, pv = make_sensors(db, building, n=2)
    other_sensor = make_group_sensor(db, building)

    flex_model = [
        {
            "sensor": battery,
            "soc_at_start": 1.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"sensor": other_sensor},
        },
        {
            "sensor": pv,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
        },
    ]
    scheduler = run_scheduler(building, flex_model, base_flex_context())
    with pytest.raises(ValueError, match="group"):
        scheduler.compute()


def test_group_entry_with_soc_at_start_raises(db, building):
    battery, pv = make_sensors(db, building, n=2)
    group_sensor = make_group_sensor(db, building)

    flex_model = [
        {
            "sensor": battery,
            "soc_at_start": 1.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"sensor": group_sensor},
        },
        {
            "sensor": pv,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"sensor": group_sensor},
        },
        {
            "sensor": group_sensor,
            "power_capacity_in_mw": ur.Quantity("2.5 MW"),
            "soc_at_start": 0.5,
        },
    ]
    scheduler = run_scheduler(building, flex_model, base_flex_context())
    with pytest.raises(ValueError, match="device-only"):
        scheduler.compute()


def test_group_mixed_commodities_raises(db, building):
    battery, pv = make_sensors(db, building, n=2)
    group_sensor = make_group_sensor(db, building)

    flex_model = [
        {
            "sensor": battery,
            "soc_at_start": 1.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "commodity": "electricity",
            "group": {"sensor": group_sensor},
        },
        {
            "sensor": pv,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "commodity": "gas",
            "group": {"sensor": group_sensor},
        },
        {
            "sensor": group_sensor,
            "power_capacity_in_mw": ur.Quantity("2.5 MW"),
        },
    ]
    scheduler = run_scheduler(building, flex_model, base_flex_context())
    with pytest.raises(ValueError, match="commodity"):
        scheduler.compute()


def test_group_entry_without_capacity_fields_raises(db, building):
    battery, pv = make_sensors(db, building, n=2)
    group_sensor = make_group_sensor(db, building)

    flex_model = [
        {
            "sensor": battery,
            "soc_at_start": 1.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"sensor": group_sensor},
        },
        {
            "sensor": pv,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"sensor": group_sensor},
        },
        {
            "sensor": group_sensor,
        },
    ]
    scheduler = run_scheduler(building, flex_model, base_flex_context())
    with pytest.raises(ValueError, match="none of"):
        scheduler.compute()


def test_group_in_single_sensor_mode_raises(db, building):
    battery = make_sensors(db, building, n=1)[0]
    group_sensor = make_group_sensor(db, building)

    scheduler = StorageScheduler(
        asset_or_sensor=battery,
        start=pd.Timestamp("2023-01-01T00:00:00", tz="Europe/Amsterdam"),
        end=pd.Timestamp("2023-01-01T04:00:00", tz="Europe/Amsterdam"),
        resolution=timedelta(hours=1),
        flex_model={
            "soc_at_start": 1.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"sensor": group_sensor},
        },
        flex_context=base_flex_context(),
    )
    scheduler.config_deserialized = True
    with pytest.raises(ValueError, match="multi-device"):
        scheduler.compute()


def test_nested_group_leaf_resolution(db, building):
    """Two-level nesting: device -> inner group -> outer group. Verify the outer
    group's aggregate power equals the sum of the leaf device's schedule (the only
    leaf here), i.e. leaf resolution skips the intermediate group."""
    battery, pv = make_sensors(db, building, n=2)
    inner_group = make_group_sensor(db, building)
    outer_group = make_group_sensor(db, building)

    flex_model = [
        {
            "sensor": battery,
            "soc_at_start": 1.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"sensor": inner_group},
        },
        {
            "sensor": pv,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "consumption_capacity": ur.Quantity("0 MW"),
            "group": {"sensor": inner_group},
        },
        {
            "sensor": inner_group,
            "power_capacity_in_mw": ur.Quantity("3 MW"),
            "group": {"sensor": outer_group},
        },
        {
            "sensor": outer_group,
            "power_capacity_in_mw": ur.Quantity("3.5 MW"),
        },
    ]
    scheduler = run_scheduler(
        building, flex_model, base_flex_context(), return_multiple=True
    )
    results = scheduler.compute()
    schedules = {
        r["sensor"]: r["data"] for r in results if r.get("name") == "storage_schedule"
    }
    assert inner_group in schedules
    assert outer_group in schedules
    expected = schedules[battery] + schedules[pv]
    assert ((schedules[inner_group] - expected).abs() < 1e-6).all()
    assert ((schedules[outer_group] - expected).abs() < 1e-6).all()


def test_group_cycle_raises(db, building):
    battery = make_sensors(db, building, n=1)[0]
    group_a = make_group_sensor(db, building)
    group_b = make_group_sensor(db, building)

    flex_model = [
        {
            "sensor": battery,
            "soc_at_start": 1.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"sensor": group_a},
        },
        {
            "sensor": group_a,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"sensor": group_b},
        },
        {
            "sensor": group_b,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"sensor": group_a},
        },
    ]
    scheduler = run_scheduler(building, flex_model, base_flex_context())
    with pytest.raises(ValueError, match="Cyclic"):
        scheduler.compute()
