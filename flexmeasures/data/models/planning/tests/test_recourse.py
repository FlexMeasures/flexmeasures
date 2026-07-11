"""Tests for the v1 per-slot recourse rules (SeitaBV/ems#231).

When ``StorageScheduler.include_response`` is set (and ``return_multiple`` is True),
the scheduler also returns, per flexible device, a ``"recourse_rule"`` entry with
per-slot values for the affine recourse rule

    setpoint(m) = clip(p + gain * (m - reference), band_min, band_max)

where ``m`` is the observed net flow of the device's commodity ("main meter").
"""

from datetime import timedelta

import numpy as np
import pandas as pd

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.data.models.planning.utils import initialize_index
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.services.utils import get_or_create_model


START = pd.Timestamp("2026-01-01T00:00:00+01:00")
RESOLUTION = timedelta(hours=1)


def _build_site(
    db,
    site_name: str,
    consumption_prices: list[float] | str,
    production_prices: list[float] | str,
    load_kw: float | None,
    n_hours: int = 4,
):
    """Build a site with a battery power sensor and (optionally) an inflexible load.

    Returns (site, battery_power_sensor, load_sensor_or_None, price_fields, end).
    Consumption is stored as negative event values on the load sensor (sensor
    convention), i.e. ``load_kw`` > 0 means the site consumes ``load_kw`` kW.
    """
    site_type = get_or_create_model(GenericAssetType, name="recourse test site")
    site = GenericAsset(name=site_name, generic_asset_type=site_type)
    db.session.add(site)
    db.session.flush()

    end = START + n_hours * RESOLUTION
    index = initialize_index(START, end, RESOLUTION)
    source = get_or_create_model(
        DataSource, name="recourse test source", type="forecaster"
    )

    battery_power = Sensor(
        name="battery power", generic_asset=site, unit="MW", event_resolution=RESOLUTION
    )
    db.session.add(battery_power)

    load_sensor = None
    if load_kw is not None:
        load_sensor = Sensor(
            name="load", generic_asset=site, unit="MW", event_resolution=RESOLUTION
        )
        db.session.add(load_sensor)
        db.session.flush()
        db.session.add_all(
            TimedBelief(
                sensor=load_sensor,
                source=source,
                event_start=dt,
                belief_time=START,
                event_value=-load_kw / 1000,  # consumption is negative on the sensor
            )
            for dt in index
        )

    price_fields = {}
    for field, prices in (
        ("consumption-price", consumption_prices),
        ("production-price", production_prices),
    ):
        if isinstance(prices, str):
            price_fields[field] = prices
            continue
        price_sensor = Sensor(
            name=f"{field} {site_name}",
            generic_asset=site,
            unit="EUR/MWh",
            event_resolution=RESOLUTION,
        )
        db.session.add(price_sensor)
        db.session.flush()
        db.session.add_all(
            TimedBelief(
                sensor=price_sensor,
                source=source,
                event_start=dt,
                belief_time=START,
                event_value=price,
            )
            for dt, price in zip(index, prices)
        )
        price_fields[field] = {"sensor": price_sensor.id}

    db.session.commit()
    return site, battery_power, load_sensor, price_fields, end


def _compute_recourse(
    site, battery_power, load_sensor, price_fields, end, site_power_capacity: str
):
    flex_model = [
        {
            "sensor": battery_power.id,
            "power-capacity": "10 kW",
            "soc-at-start": "0.005 MWh",
            "soc-min": "0 MWh",
            "soc-max": "0.02 MWh",
            # Opt in through the flex-model field (rather than the scheduler
            # attribute), which also covers the schema wiring.
            "include-response": True,
        }
    ]
    flex_context = {
        **price_fields,
        "site-power-capacity": site_power_capacity,
    }
    if load_sensor is not None:
        flex_context["inflexible-device-sensors"] = [load_sensor.id]

    scheduler = StorageScheduler(
        asset_or_sensor=site,
        start=START,
        end=end,
        resolution=RESOLUTION,
        belief_time=START,
        flex_model=flex_model,
        flex_context=flex_context,
        return_multiple=True,
    )
    results = scheduler.compute()
    rules = [r for r in results if r["name"] == "recourse_rule"]
    assert len(rules) == 1
    assert rules[0]["sensor"] == battery_power
    return rules[0]["data"]


def test_recourse_band_and_reference_hand_verified(app, db):
    """Battery + inflexible load: hand-verified band, reference and gain per slot.

    Setup (all powers in kW, consumption positive; 4 hourly slots):

    - battery: power capacity 10, soc-at-start 5 kWh, soc-min 0, soc-max 20 kWh;
    - constant inflexible load of 8;
    - site power capacity 15 (so the battery can charge at most 7);
    - prices (both directions, so symmetric): [10, 50, 10, 45] EUR/MWh.

    The optimal plan is p = [7, -10, 7, -9] (charge at max in cheap hours — limited
    by the site fuse — and discharge at max in expensive hours, ending empty).

    Hand-derived recourse values:

    - reference (net site flow, incl. the battery's own p): [15, -2, 15, -1];
    - band_max: 7 in every slot (site headroom 15 - 8 = 7 binds before the 10 device cap);
    - band_min per slot from device cap (-10), site headroom (-23) and stock
      reachability given the planned SoC at the start of the slot [5, 12, 2, 9] kWh:
      discharging below -SoC/1h would make the SoC negative, so
      band_min = max(-10, -SoC) = [-5, -10, -2, -9];
    - gain: the site capacity binds at the optimum in slots 0 and 2 (net flow 15),
      so the battery (the only flexible device) gets K = -1 there and K = 0 elsewhere.
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (hand-verified)",
        consumption_prices=[10, 50, 10, 45],
        production_prices=[10, 50, 10, 45],
        load_kw=8,
    )
    data = _compute_recourse(
        site, battery_power, load_sensor, price_fields, end, site_power_capacity="15 kW"
    )

    np.testing.assert_allclose(
        data["p"], [0.007, -0.010, 0.007, -0.009], atol=1e-6, err_msg="planned power"
    )
    np.testing.assert_allclose(
        data["reference"], [0.015, -0.002, 0.015, -0.001], atol=1e-6, err_msg="m̂"
    )
    np.testing.assert_allclose(
        data["band_max"], [0.007, 0.007, 0.007, 0.007], atol=1e-6, err_msg="band_max"
    )
    np.testing.assert_allclose(
        data["band_min"],
        [-0.005, -0.010, -0.002, -0.009],
        atol=1e-6,
        err_msg="band_min",
    )
    np.testing.assert_allclose(data["gain"], [-1, 0, -1, 0], err_msg="gain")


def test_recourse_rule_property_within_band(app, db):
    """Property check: applying the rule for sampled meter observations never violates
    the device's power capacity, and — for within-band surprises — the site capacity.

    The surprise is attributed to the inflexible load: if the meter shows m instead of
    the reference m̂, the actual load is (m - p) instead of (m̂ - p). The new net site
    flow after applying the rule is then (m - p) + setpoint(m).
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (property test)",
        consumption_prices=[10, 50, 10, 45],
        production_prices=[10, 50, 10, 45],
        load_kw=8,
    )
    data = _compute_recourse(
        site, battery_power, load_sensor, price_fields, end, site_power_capacity="15 kW"
    )

    device_capacity = 0.010  # MW
    site_capacity = 0.015  # MW
    eps = 1e-9

    rng = np.random.default_rng(42)
    for _, row in data.iterrows():
        p, gain, lo, hi, m_hat = (
            row["p"],
            row["gain"],
            row["band_min"],
            row["band_max"],
            row["reference"],
        )
        band_width = hi - lo
        # Sample meter observations well beyond the band, too (the clip must protect us).
        surprises = rng.uniform(-3 * band_width - 0.01, 3 * band_width + 0.01, size=50)
        for s in surprises:
            m = m_hat + s
            unclipped = p + gain * (m - m_hat)
            setpoint = np.clip(unclipped, lo, hi)

            # The setpoint never violates the device's power capacity.
            assert -device_capacity - eps <= setpoint <= device_capacity + eps

            # In K=0 slots, the rule follows the plan.
            if gain == 0:
                assert setpoint == p

            # For within-band surprises, the responding device restores the site
            # position: the new net flow respects the site capacity.
            if gain == -1 and lo - eps <= unclipped <= hi + eps:
                new_net = (m - p) + setpoint
                assert -site_capacity - eps <= new_net <= site_capacity + eps


def test_recourse_gain_price_asymmetry(app, db):
    """K = -1 when the production price (0) differs from the consumption price (50)."""
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (asymmetric prices)",
        consumption_prices="50 EUR/MWh",
        production_prices="0 EUR/MWh",
        load_kw=None,
    )
    data = _compute_recourse(
        site,
        battery_power,
        load_sensor,
        price_fields,
        end,
        site_power_capacity="100 kW",
    )
    np.testing.assert_allclose(data["gain"], -1)
    # With ample site headroom, the band is set by the device cap and SoC reachability.
    # The battery idles at SoC 5 kWh (of 0..20 kWh): discharging more than 5 kW for an
    # hour would make the SoC negative, while charging is only device-capped (10 kW).
    np.testing.assert_allclose(data["band_min"], -0.005, atol=1e-6)
    np.testing.assert_allclose(data["band_max"], 0.010, atol=1e-6)


def test_recourse_gain_flat_symmetric_prices(app, db):
    """K = 0 with flat symmetric prices and a non-binding site capacity."""
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (flat symmetric prices)",
        consumption_prices="50 EUR/MWh",
        production_prices="50 EUR/MWh",
        load_kw=None,
    )
    data = _compute_recourse(
        site,
        battery_power,
        load_sensor,
        price_fields,
        end,
        site_power_capacity="100 kW",
    )
    np.testing.assert_allclose(data["gain"], 0)


def test_recourse_gain_mixed_day(app, db):
    """The gain classification is per-slot: on a mixed day, K flips slot by slot.

    Slots 0 and 2 have symmetric positive prices (50/50 EUR/MWh) and slack site
    capacity, so they stay K = 0 even though other slots of the same day are
    asymmetric. Slots 1 and 3 have production price 0 != consumption price 50,
    so they get K = -1.
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (mixed day)",
        consumption_prices=[50, 50, 50, 50],
        production_prices=[50, 0, 50, 0],
        load_kw=None,
    )
    data = _compute_recourse(
        site,
        battery_power,
        load_sensor,
        price_fields,
        end,
        site_power_capacity="100 kW",
    )
    np.testing.assert_allclose(data["gain"], [0, -1, 0, -1], err_msg="gain per slot")
