"""Repro test: does a soft site-consumption-capacity bind in a multi-device job?

Observed in the FLEXED community co-simulation: with a single flexible device,
a tightened site-consumption-capacity (with relax-site-capacity-constraints
breach pricing) binds; with two devices scheduled in the same job (heater +
battery), the schedule ignored the capacity entirely.
"""

from datetime import timedelta

import pandas as pd

from flexmeasures import Sensor
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.utils.unit_utils import ur


def make_device(db, building, name):
    sensor = Sensor(
        name=name,
        generic_asset=building,
        event_resolution=timedelta(hours=1),
        unit="MW",
    )
    db.session.add(sensor)
    return sensor


def run_schedule(db, building, n_devices: int) -> list[pd.Series]:
    """One-hour horizon; every device wants to charge at full power (paid to consume).

    Site consumption capacity is 0.5 MW (soft, with the same 10000 EUR/kW breach
    price the relax-site-capacity-constraints flag defaults to), physical site
    capacity 5 MW. Optimal total consumption is 0.5 MW regardless of device count.
    """
    sensors = [
        make_device(db, building, f"repro device {d} of {n_devices}")
        for d in range(n_devices)
    ]
    db.session.commit()

    start = pd.Timestamp("2020-01-01T00:00:00", tz="Europe/Amsterdam")
    end = start + timedelta(hours=1)
    resolution = timedelta(hours=1)

    flex_model = [
        {
            "sensor": sensor,
            "soc_at_start": 0.0,
            "soc_min": 0.0,
            "soc_max": 2.0,
            "power_capacity_in_mw": ur.Quantity("1 MW"),
            "consumption_capacity": ur.Quantity("1 MW"),
            "production_capacity": ur.Quantity("0 MW"),
            "prefer_charging_sooner": False,
            "prefer_curtailing_later": False,
        }
        for sensor in sensors
    ]
    scheduler = StorageScheduler(
        asset_or_sensor=building,
        start=start,
        end=end,
        resolution=resolution,
        flex_model=flex_model,
        flex_context={
            # Being paid to consume: every device wants its full 1 MW
            "consumption_price": ur.Quantity("-100 EUR/MWh"),
            "production_price": ur.Quantity("-100 EUR/MWh"),
            "shared_currency_unit": "EUR",
            "ems_power_capacity_in_mw": ur.Quantity("5 MW"),
            "ems_consumption_capacity_in_mw": ur.Quantity("0.5 MW"),
            # Same defaults the relax-site-capacity-constraints flag fills in
            "ems_consumption_breach_price": ur.Quantity("10000 EUR/kW"),
            "ems_production_breach_price": ur.Quantity("10000 EUR/kW"),
        },
        return_multiple=True,
    )
    scheduler.config_deserialized = True
    results = scheduler.compute()
    return [
        r["data"]
        for r in results
        if r.get("name") == "storage_schedule" and r.get("sensor") in sensors
    ]


def test_site_consumption_capacity_binds_single_device(db, building):
    schedules = run_schedule(db, building, n_devices=1)
    total = sum(schedules)
    assert total.max() <= 0.5 + 1e-3, f"single-device schedule breaches: {total.values}"


def test_site_consumption_capacity_binds_two_devices(db, building):
    schedules = run_schedule(db, building, n_devices=2)
    total = sum(schedules)
    assert total.max() <= 0.5 + 1e-3, f"two-device schedule breaches: {total.values}"


def test_site_capacity_binds_with_db_flex_model_child(
    db, building, setup_markets, add_market_prices
):
    """Full-path repro of the community co-simulation's heater+battery job.

    The trigger passes a single (heater-like) device flex-model dict; the
    battery enters via its child asset's DB flex-model (no "sensor" key, only
    a "consumption" output reference), merged by collect_flex_config. The
    site-consumption-capacity comes from the parent's DB flex-context as a
    sensor, alongside the relax-site-capacity-constraints flag, and the full
    deserialization path runs (config_deserialized is NOT set).
    """
    from flexmeasures import Asset as GenericAsset
    from flexmeasures.data.models.generic_assets import GenericAssetType
    from flexmeasures.data.models.data_sources import DataSource
    from flexmeasures.data.models.time_series import TimedBelief
    from sqlalchemy import select

    # Heater-like device on the building itself
    heater = make_device(db, building, "repro heater power")

    # Battery child asset with a DB flex-model, like the community case
    battery_asset_type = db.session.execute(
        select(GenericAssetType).filter_by(name="battery")
    ).scalar_one_or_none() or GenericAssetType(name="battery")
    battery_asset = GenericAsset(
        name="repro battery",
        generic_asset_type=battery_asset_type,
        parent_asset=building,
        owner=building.owner,
    )
    db.session.add_all([battery_asset_type, battery_asset])
    db.session.flush()
    battery_power = Sensor(
        name="repro battery power",
        generic_asset=battery_asset,
        unit="MW",
        event_resolution=timedelta(hours=1),
    )
    db.session.add(battery_power)
    db.session.flush()
    battery_asset.flex_model = {
        "consumption": {"sensor": battery_power.id},
        "soc-min": "0 MWh",
        "soc-max": "2 MWh",
        "soc-at-start": "0 MWh",
        "power-capacity": "1 MW",
    }

    # Site-consumption-capacity sensor on the building, with a 0.5 MW belief
    cap_sensor = Sensor(
        name="repro site consumption capacity",
        generic_asset=building,
        unit="MW",
        event_resolution=timedelta(hours=1),
    )
    db.session.add(cap_sensor)
    db.session.flush()
    source = db.session.execute(
        select(DataSource).filter_by(name="Seita")
    ).scalar_one_or_none() or DataSource(name="Seita", type="scheduler")
    start = pd.Timestamp("2015-01-02T00:00:00", tz="Europe/Amsterdam")
    db.session.add(
        TimedBelief(
            sensor=cap_sensor,
            source=source,
            event_start=start,
            belief_time=start - timedelta(hours=1),
            event_value=0.5,
        )
    )
    building.flex_context = {
        **building.flex_context,
        "site-consumption-capacity": {"sensor": cap_sensor.id},
    }
    db.session.commit()

    end = start + timedelta(hours=1)
    scheduler = StorageScheduler(
        asset_or_sensor=building,
        start=start,
        end=end,
        resolution=timedelta(hours=1),
        # Serialized, CEM-style single-device flex-model; battery merges from DB
        flex_model={
            "sensor": heater.id,
            "soc-unit": "MWh",
            "soc-at-start": 0,
            "soc-min": 0,
            "soc-max": 2,
            "consumption-capacity": "1 MW",
            "production-capacity": "0 MW",
        },
        flex_context={
            # Being paid to consume: both devices want their full 1 MW
            "consumption-price": "-100 EUR/MWh",
            "production-price": "-100 EUR/MWh",
            "site-power-capacity": "5 MVA",
            "relax-soc-constraints": True,
            "relax-site-capacity-constraints": True,
        },
        return_multiple=True,
    )
    results = scheduler.compute()
    schedules = [
        r["data"]
        for r in results
        if r.get("name") in ("storage_schedule", "consumption_schedule")
        and r.get("sensor") is not None
    ]
    assert (
        len(schedules) >= 2
    ), f"expected heater+battery schedules, got {len(schedules)}"
    total = sum(schedules)
    print(
        "PER-DEVICE:", [list(s.values) for s in schedules], "TOTAL:", list(total.values)
    )
    assert (
        total.max() <= 0.5 + 1e-3
    ), f"merged-job schedule breaches the 0.5 MW site capacity: {[s.values for s in schedules]}"
