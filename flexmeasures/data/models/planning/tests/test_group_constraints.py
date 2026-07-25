import uuid
from datetime import timedelta

import pytest
import pandas as pd

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
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


def make_sub_asset(db, building):
    """Create a child asset (e.g. an inverter/sub-EMS) under `building`."""
    asset_type = GenericAssetType(name=_unique_name("group test asset type"))
    db.session.add(asset_type)
    asset = GenericAsset(
        name=_unique_name("group test sub-asset"),
        generic_asset_type=asset_type,
        parent_asset=building,
        owner=building.owner,
    )
    db.session.add(asset)
    db.session.commit()
    return asset


def make_output_sensor(db, asset, unit="MW"):
    s = Sensor(
        name=_unique_name("output sensor"),
        generic_asset=asset,
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


def test_group_asset_ref_hard_cap(db, building):
    """An asset-referenced group entry (no power sensor of its own) still caps the
    aggregate power of its members, and saves the aggregate on its consumption output
    sensor (consumption-only case: full profile, consumption positive)."""
    battery, pv = make_sensors(db, building, n=2)
    inverter = make_sub_asset(db, building)
    consumption_sensor = make_output_sensor(db, inverter)

    flex_model = [
        {
            "sensor": battery,
            "soc_at_start": 1.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "consumption_capacity": ur.Quantity("2 MW"),
            "production_capacity": ur.Quantity("2 MW"),
            "group": {"asset": inverter},
        },
        {
            "sensor": pv,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "consumption_capacity": ur.Quantity("0 MW"),
            "production_capacity": ur.Quantity("2 MW"),
            "group": {"asset": inverter},
        },
        {
            "asset": inverter,
            "power_capacity_in_mw": ur.Quantity("2.5 MW"),
            "consumption": {"sensor": consumption_sensor},
        },
    ]
    scheduler = run_scheduler(
        building, flex_model, base_flex_context(), return_multiple=True
    )
    results = scheduler.compute()

    storage_schedules = {
        r["sensor"]: r["data"] for r in results if r.get("name") == "storage_schedule"
    }
    assert battery in storage_schedules
    assert pv in storage_schedules
    # The group entry has no power sensor of its own, so it isn't in storage_schedules.
    assert not any(
        getattr(sensor, "asset", None) == inverter for sensor in storage_schedules
    )

    consumption_schedules = {
        r["sensor"]: r["data"]
        for r in results
        if r.get("name") == "consumption_schedule"
    }
    assert consumption_sensor in consumption_schedules
    aggregate = consumption_schedules[consumption_sensor]
    assert (aggregate.abs() <= 2.5 + 1e-6).all()
    assert (
        (storage_schedules[battery] + storage_schedules[pv] - aggregate).abs() < 1e-6
    ).all()


def test_group_asset_ref_production_only_output(db, building):
    """An asset-referenced group entry with only a production output sensor gets the
    full aggregate profile in native (consumption-positive) convention; sign inversion
    to production-positive happens downstream in make_schedule."""
    battery, pv = make_sensors(db, building, n=2)
    inverter = make_sub_asset(db, building)
    production_sensor = make_output_sensor(db, inverter)

    flex_model = [
        {
            "sensor": battery,
            "soc_at_start": 1.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"asset": inverter},
        },
        {
            "sensor": pv,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "consumption_capacity": ur.Quantity("0 MW"),
            "group": {"asset": inverter},
        },
        {
            "asset": inverter,
            "power_capacity_in_mw": ur.Quantity("2.5 MW"),
            "production": {"sensor": production_sensor},
        },
    ]
    scheduler = run_scheduler(
        building, flex_model, base_flex_context(), return_multiple=True
    )
    results = scheduler.compute()

    storage_schedules = {
        r["sensor"]: r["data"] for r in results if r.get("name") == "storage_schedule"
    }
    production_schedules = {
        r["sensor"]: r["data"]
        for r in results
        if r.get("name") == "production_schedule"
    }
    assert production_sensor in production_schedules
    expected = storage_schedules[battery] + storage_schedules[pv]
    assert ((production_schedules[production_sensor] - expected).abs() < 1e-6).all()


def test_group_asset_ref_both_outputs_split(db, building):
    """An asset-referenced group entry with both consumption and production output
    sensors gets the clip-split of the aggregate: non-negative to consumption,
    non-positive to production."""
    battery, pv = make_sensors(db, building, n=2)
    inverter = make_sub_asset(db, building)
    consumption_sensor = make_output_sensor(db, inverter)
    production_sensor = make_output_sensor(db, inverter)

    flex_model = [
        {
            "sensor": battery,
            "soc_at_start": 1.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"asset": inverter},
        },
        {
            "sensor": pv,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "consumption_capacity": ur.Quantity("0 MW"),
            "group": {"asset": inverter},
        },
        {
            "asset": inverter,
            "power_capacity_in_mw": ur.Quantity("2.5 MW"),
            "consumption": {"sensor": consumption_sensor},
            "production": {"sensor": production_sensor},
        },
    ]
    scheduler = run_scheduler(
        building, flex_model, base_flex_context(), return_multiple=True
    )
    results = scheduler.compute()

    storage_schedules = {
        r["sensor"]: r["data"] for r in results if r.get("name") == "storage_schedule"
    }
    consumption_schedules = {
        r["sensor"]: r["data"]
        for r in results
        if r.get("name") == "consumption_schedule"
    }
    production_schedules = {
        r["sensor"]: r["data"]
        for r in results
        if r.get("name") == "production_schedule"
    }
    aggregate = storage_schedules[battery] + storage_schedules[pv]
    assert (
        (consumption_schedules[consumption_sensor] - aggregate.clip(lower=0)).abs()
        < 1e-6
    ).all()
    assert (
        (production_schedules[production_sensor] - aggregate.clip(upper=0)).abs() < 1e-6
    ).all()
    # Consistency: consumption plus production reconstructs the full aggregate.
    assert (
        (
            consumption_schedules[consumption_sensor]
            + production_schedules[production_sensor]
            - aggregate
        ).abs()
        < 1e-6
    ).all()


def test_group_asset_ref_dangling_raises(db, building):
    battery = make_sensors(db, building, n=1)[0]
    other_asset = make_sub_asset(db, building)

    flex_model = [
        {
            "sensor": battery,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"asset": other_asset},
        },
    ]
    scheduler = run_scheduler(building, flex_model, base_flex_context())
    with pytest.raises(ValueError, match="group"):
        scheduler.compute()


def test_group_asset_ref_with_sensor_raises(db, building):
    """An asset-referenced group entry must not also carry a `sensor` field."""
    battery, pv = make_sensors(db, building, n=2)
    inverter = make_sub_asset(db, building)
    bogus_sensor = make_group_sensor(db, building)

    flex_model = [
        {
            "sensor": battery,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"asset": inverter},
        },
        {
            "sensor": pv,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"asset": inverter},
        },
        {
            "asset": inverter,
            "sensor": bogus_sensor,
            "power_capacity_in_mw": ur.Quantity("2.5 MW"),
        },
    ]
    scheduler = run_scheduler(building, flex_model, base_flex_context())
    with pytest.raises(ValueError, match="asset-"):
        scheduler.compute()


def test_nested_group_mixed_ref_kinds(db, building):
    """Inner group referenced by asset, outer group referenced by sensor: leaf
    resolution must work transitively across both kinds."""
    battery = make_sensors(db, building, n=1)[0]
    inverter = make_sub_asset(db, building)
    outer_group_sensor = make_group_sensor(db, building)

    flex_model = [
        {
            "sensor": battery,
            "soc_at_start": 1.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("2 MW"),
            "group": {"asset": inverter},
        },
        {
            "asset": inverter,
            "power_capacity_in_mw": ur.Quantity("3 MW"),
            "group": {"sensor": outer_group_sensor},
        },
        {
            "sensor": outer_group_sensor,
            "power_capacity_in_mw": ur.Quantity("3.5 MW"),
        },
    ]
    scheduler = run_scheduler(
        building, flex_model, base_flex_context(), return_multiple=True
    )
    results = scheduler.compute()
    storage_schedules = {
        r["sensor"]: r["data"] for r in results if r.get("name") == "storage_schedule"
    }
    assert outer_group_sensor in storage_schedules
    assert (
        (storage_schedules[outer_group_sensor] - storage_schedules[battery]).abs()
        < 1e-6
    ).all()


def test_pure_db_tree_group_constraint(db, building):
    """End-to-end (planning-level): the entire flex-model lives on the asset tree in
    the DB (no flex-model entries are passed to the scheduler at all). A site asset
    (``building``) has two child assets (battery-like and PV-like) that are both
    asset-only device entries (no power sensor of their own; results are saved via
    consumption/production output sensors) belonging to a group referenced by a third
    child asset (an "inverter"), which itself defines the group's hard power-capacity
    and saves the group's aggregate via its own consumption output sensor.

    Triggering the site asset with an empty flex-model list should still produce a
    correctly constrained schedule, entirely from `GenericAsset.flex_model` attributes,
    via `Scheduler.collect_flex_config`.
    """
    inverter = make_sub_asset(db, building)
    battery_asset = make_sub_asset(db, building)
    pv_asset = make_sub_asset(db, building)

    inverter_consumption_sensor = make_output_sensor(db, inverter)
    battery_consumption_sensor = make_output_sensor(db, battery_asset)
    battery_production_sensor = make_output_sensor(db, battery_asset)
    pv_production_sensor = make_output_sensor(db, pv_asset)

    # Store the flex-model entirely on the assets in the DB (asset-only entries: no
    # "sensor" key, so results are saved via consumption/production output sensors).
    battery_asset.flex_model = {
        "power-capacity": "2 MW",
        "consumption-capacity": "2 MW",
        "production-capacity": "2 MW",
        "group": {"asset": inverter.id},
        "consumption": {"sensor": battery_consumption_sensor.id},
        "production": {"sensor": battery_production_sensor.id},
    }
    pv_asset.flex_model = {
        "power-capacity": "2 MW",
        "consumption-capacity": "0 MW",
        "production-capacity": "2 MW",
        "group": {"asset": inverter.id},
        "production": {"sensor": pv_production_sensor.id},
    }
    inverter.flex_model = {
        "power-capacity": "2.5 MW",
        "consumption": {"sensor": inverter_consumption_sensor.id},
    }
    db.session.add_all([battery_asset, pv_asset, inverter])
    db.session.commit()

    scheduler = StorageScheduler(
        asset_or_sensor=building,
        start=pd.Timestamp("2023-01-01T00:00:00", tz="Europe/Amsterdam"),
        end=pd.Timestamp("2023-01-01T04:00:00", tz="Europe/Amsterdam"),
        resolution=timedelta(hours=1),
        flex_model=[],  # entirely DB-driven
        # `building`'s own flex-context (in the DB) already sets a large
        # site-power-capacity; override the (unpopulated) sensor-based
        # consumption-price with fixed quantities here. Real deserialization
        # (collect_flex_config + schema loading) is exercised, unlike in the other
        # tests in this file (which bypass it).
        flex_context={
            "consumption-price": "100 EUR/MWh",
            "production-price": "100 EUR/MWh",
        },
        return_multiple=True,
    )
    results = scheduler.compute()

    consumption_schedules = {
        r["sensor"]: r["data"]
        for r in results
        if r.get("name") == "consumption_schedule"
    }
    production_schedules = {
        r["sensor"]: r["data"]
        for r in results
        if r.get("name") == "production_schedule"
    }

    assert inverter_consumption_sensor in consumption_schedules
    aggregate = consumption_schedules[inverter_consumption_sensor]
    # Hard cap on the group's aggregate power respected.
    assert (aggregate.abs() <= 2.5 + 1e-6).all()

    # The aggregate equals the sum of the (signed, consumption-positive) member
    # device schedules, reconstructed from their consumption/production outputs.
    battery_signed = consumption_schedules.get(
        battery_consumption_sensor,
        pd.Series(0.0, index=aggregate.index),
    ) + production_schedules.get(
        battery_production_sensor, pd.Series(0.0, index=aggregate.index)
    )
    pv_signed = production_schedules.get(
        pv_production_sensor, pd.Series(0.0, index=aggregate.index)
    )
    assert ((battery_signed + pv_signed - aggregate).abs() < 1e-6).all()
