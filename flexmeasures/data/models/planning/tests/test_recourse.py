"""Tests for the per-slot reaction rules (FlexMeasures issue #2894).

When a flex-model device sets ``react`` (and ``return_multiple`` is True),
the scheduler also returns, per flexible device, a ``"recourse_rule"`` entry with per-slot values for the reaction rule:

    setpoint = clip(p - react * (m_uncontrolled - reference), band)

where ``m_uncontrolled`` is the measured uncontrolled power at the connection,
``reference`` the uncontrolled power the plan assumed,
and ``band`` a list of (min, max) power ranges the device may move within.

The reaction directions, the reaction time and the retrigger flag are not yet exposed through the public schemas;
the tests set their internal keys on the deserialized flex config.
"""

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.data.models.planning.utils import initialize_index
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.services.utils import get_or_create_model

# The rules derive from the plan, so they must hold under each solver backend.
RUN_UNDER_EACH_SOLVER = True

START = pd.Timestamp("2026-01-01T00:00:00+01:00")
RESOLUTION = timedelta(hours=1)
TOLERANCE = 1e-6  # MW


def _build_site(
    db,
    site_name: str,
    consumption_prices: list[float] | str,
    production_prices: list[float] | str,
    load_kw: float | list[float] | None,
    n_hours: int = 4,
):
    """Build a site with a battery power sensor and (optionally) an uncontrolled load.

    Returns (site, battery_power_sensor, load_sensor_or_None, price_fields, end).
    The load sensor is listed under ``inflexible-consumption``, so it stores consumption as positive values,
    i.e. ``load_kw`` > 0 means the site consumes ``load_kw`` kW (and < 0 means it produces), per slot when given as a list.
    A site built before (by the same test under another solver backend) is returned as is.
    """
    end = START + n_hours * RESOLUTION
    site = db.session.query(GenericAsset).filter_by(name=site_name).one_or_none()
    if site is not None:
        sensors = {sensor.name: sensor for sensor in site.sensors}
        price_fields = {
            field: (
                prices
                if isinstance(prices, str)
                else {"sensor": sensors[f"{field} {site_name}"].id}
            )
            for field, prices in (
                ("consumption-price", consumption_prices),
                ("production-price", production_prices),
            )
        }
        return site, sensors["battery power"], sensors.get("load"), price_fields, end

    site_type = get_or_create_model(GenericAssetType, name="recourse test site")
    site = GenericAsset(name=site_name, generic_asset_type=site_type)
    db.session.add(site)
    db.session.flush()

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
        loads = load_kw if isinstance(load_kw, list) else [load_kw] * n_hours
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
                event_value=load / 1000,
            )
            for dt, load in zip(index, loads)
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


def _battery_flex_model(sensor: Sensor, react: bool = True, **extra) -> dict:
    return {
        "sensor": sensor.id,
        "power-capacity": "10 kW",
        "soc-at-start": "0.005 MWh",
        "soc-min": "0 MWh",
        "soc-max": "0.02 MWh",
        "react": react,
        **extra,
    }


def _compute_recourse(
    site,
    battery_power,
    load_sensor,
    price_fields,
    end,
    site_power_capacity: str,
    flex_model: list[dict] | None = None,
    internal_device_keys: dict[int, dict] | None = None,
    internal_context_keys: dict | None = None,
) -> dict[int, pd.DataFrame]:
    """Schedule the site and return each device's reaction rule data by sensor ID.

    ``internal_device_keys`` (by device index) and ``internal_context_keys`` are set on the deserialized flex config,
    the way the scheduler reads keys the public schemas do not expose yet.
    """
    if flex_model is None:
        flex_model = [_battery_flex_model(battery_power)]
    flex_context = {
        **price_fields,
        "site-power-capacity": site_power_capacity,
    }
    if load_sensor is not None:
        flex_context["inflexible-consumption"] = [{"sensor": load_sensor.id}]

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
    scheduler.deserialize_config()
    for d, keys in (internal_device_keys or {}).items():
        scheduler.flex_model[d].update(keys)
    scheduler.flex_context.update(internal_context_keys or {})
    results = scheduler.compute()
    rules = [r for r in results if r["name"] == "recourse_rule"]
    assert len(rules) == len(flex_model)
    return {rule["sensor"].id: rule for rule in rules}


def _clip_to_band(value: float, band: list[tuple[float, float]]) -> float:
    """Clip a value to the nearest point of a band made of several ranges."""
    candidates = [min(max(value, lo), hi) for lo, hi in band]
    return min(candidates, key=lambda candidate: abs(candidate - value))


def _assert_bands_are_well_formed(data: pd.DataFrame):
    """Every band is a sorted list of disjoint finite ranges, one of which holds the planned power."""
    for _, row in data.iterrows():
        band = row["band"]
        assert len(band) >= 1
        previous_hi = -np.inf
        for lo, hi in band:
            assert np.isfinite(lo) and np.isfinite(
                hi
            ), "a power-capacity bounds every side"
            assert lo <= hi
            assert lo > previous_hi
            previous_hi = hi
        assert np.isclose(_clip_to_band(row["p"], band), row["p"], atol=TOLERANCE)
        if row["react"] == 0:
            assert band == [(row["p"], row["p"])]


def test_reaction_band_reference_and_react_hand_verified(app, db):
    """Battery + uncontrolled load: hand-verified band, reference and react share per slot.

    Setup (all powers in kW, consumption positive; 4 hourly slots):

    - battery: power capacity 10, soc-at-start 5 kWh, soc-min 0, soc-max 20 kWh;
    - constant uncontrolled load of 8;
    - site power capacity 15 (so the battery can charge at most 7);
    - prices (both directions, so symmetric): [10, 50, 10, 45] EUR/MWh.

    The optimal plan is p = [7, -10, 7, -9]:
    charge at max in cheap hours (limited by the site fuse) and discharge at max in expensive hours, ending empty.

    Hand-derived reaction values:

    - reference: the uncontrolled load, [8, 8, 8, 8], without the battery's own plan;
    - react: the site capacity binds at the optimum in slots 0 and 2 (net flow 15), so the battery gets 1 there and 0 elsewhere;
    - band in the reacting slots, from the device's own limits only (the site headroom does not narrow it):
      the device cap (±10) and the stock reachability given the planned SoC at the start of the slot (5 and 2 kWh),
      so slot 0 gets [-5, 10] and slot 2 gets [-2, 10];
    - band in the other slots: just the planned power.
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
    )[battery_power.id]["data"]

    np.testing.assert_allclose(
        data["p"], [0.007, -0.010, 0.007, -0.009], atol=TOLERANCE, err_msg="plan"
    )
    np.testing.assert_allclose(
        data["reference"], [0.008, 0.008, 0.008, 0.008], atol=TOLERANCE, err_msg="L̂"
    )
    np.testing.assert_allclose(data["react"], [1, 0, 1, 0], err_msg="react")
    bands = data["band"].tolist()
    np.testing.assert_allclose(bands[0], [(-0.005, 0.010)], atol=TOLERANCE)
    np.testing.assert_allclose(bands[2], [(-0.002, 0.010)], atol=TOLERANCE)
    np.testing.assert_allclose(bands[1], [(-0.010, -0.010)], atol=TOLERANCE)
    np.testing.assert_allclose(bands[3], [(-0.009, -0.009)], atol=TOLERANCE)


@pytest.mark.parametrize("load_kw", [8, None])
def test_house_as_forecast_keeps_the_plan(app, db, load_kw):
    """When the connection behaves as forecast, every setpoint equals the plan, whatever the react share.

    That holds when the reference is the uncontrolled forecast (so the surprise is zero) and the band contains the plan.
    Without any uncontrolled device, the reference is 0, not null.
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name=f"Recourse site (as forecast, load {load_kw})",
        consumption_prices=[10, 50, 10, 45],
        production_prices=[10, 50, 10, 45],
        load_kw=load_kw,
    )
    data = _compute_recourse(
        site, battery_power, load_sensor, price_fields, end, site_power_capacity="15 kW"
    )[battery_power.id]["data"]

    _assert_bands_are_well_formed(data)
    uncontrolled = 0.008 if load_kw else 0.0
    np.testing.assert_allclose(data["reference"], uncontrolled, atol=TOLERANCE)
    for _, row in data.iterrows():
        measured_uncontrolled = row["reference"]  # the house behaves as forecast
        for react in (0, 1):
            setpoint = _clip_to_band(
                row["p"] - react * (measured_uncontrolled - row["reference"]),
                row["band"],
            )
            assert setpoint == row["p"]


def test_react_classes_on_a_mixed_day(app, db):
    """The react share is classified per slot, following the three rules of the reaction rules.

    Four hourly slots (prices in EUR/MWh as consumption/production, powers in kW):

    - slot 0, cheap night (30/30, nothing uncontrolled): the battery charges 4 kW to cover the evening, so react 0;
    - slot 1, sunny midday (50/5, 6 kW of PV): the battery absorbs all PV, so the planned connection power is zero
      while the production price is below the consumption price, so react 1;
    - slot 2, expensive evening (100/100, nothing uncontrolled): the battery discharges its full 10 kW,
      well within the 15 kW site capacity, so react 0;
    - slot 3, fuse-binding (20/20, 20 kW of load): the battery must discharge 5 kW to keep the connection at 15 kW, so react 1.
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (mixed day)",
        consumption_prices=[30, 50, 100, 20],
        production_prices=[30, 5, 100, 20],
        load_kw=[0, -6, 0, 20],
    )
    data = _compute_recourse(
        site, battery_power, load_sensor, price_fields, end, site_power_capacity="15 kW"
    )[battery_power.id]["data"]

    np.testing.assert_allclose(
        data["p"], [0.004, 0.006, -0.010, -0.005], atol=TOLERANCE, err_msg="plan"
    )
    np.testing.assert_allclose(
        data["reference"], [0, -0.006, 0, 0.020], atol=TOLERANCE, err_msg="L̂"
    )
    np.testing.assert_allclose(data["react"], [0, 1, 0, 1], err_msg="react per slot")
    _assert_bands_are_well_formed(data)


def test_bands_respect_operation_modes(app, db):
    """A device with operation modes gets a band of several ranges, none of which spans a hole between modes.

    The battery can be off, consume between 2 and 5 kW, or produce between 2 and 5 kW.
    With a production price of zero, every slot is a reacting slot.
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (operation modes)",
        consumption_prices="50 EUR/MWh",
        production_prices="0 EUR/MWh",
        load_kw=None,
    )
    modes = [
        {"consumption-range": ["0 kW", "0 kW"]},
        {"consumption-range": ["2 kW", "5 kW"]},
        {"production-range": ["2 kW", "5 kW"]},
    ]
    signed_modes = [(0, 0), (0.002, 0.005), (-0.005, -0.002)]
    data = _compute_recourse(
        site,
        battery_power,
        load_sensor,
        price_fields,
        end,
        site_power_capacity="100 kW",
        flex_model=[
            _battery_flex_model(
                battery_power, **{"power-capacity": "5 kW", "operation-modes": modes}
            )
        ],
    )[battery_power.id]["data"]

    _assert_bands_are_well_formed(data)
    np.testing.assert_allclose(data["react"], 1)
    for _, row in data.iterrows():
        for lo, hi in row["band"]:
            assert any(
                mode_lo - TOLERANCE <= lo and hi <= mode_hi + TOLERANCE
                for mode_lo, mode_hi in signed_modes
            ), f"range ({lo}, {hi}) spans a hole between the operation modes"
        # Idle at the start (5 kWh of 0..20 kWh), the battery may go anywhere within its modes.
        if np.isclose(row["p"], 0, atol=TOLERANCE):
            np.testing.assert_allclose(
                row["band"], [(-0.005, -0.002), (0, 0), (0.002, 0.005)], atol=TOLERANCE
            )


@pytest.mark.parametrize(
    ["internal_keys", "expected_react", "expected_band"],
    [
        # Only consumption-up: the band opens above the (idle) plan only.
        (
            {"reaction_directions": ["consumption-up"]},
            1,
            [(0, 0.010)],
        ),
        # Only production-up: the band opens below the plan, as far as the 5 kWh in stock allow.
        (
            {"reaction_directions": ["production-up"]},
            1,
            [(-0.005, 0)],
        ),
        # A device slower than one scheduling step gets react 0, and a band of just its plan.
        (
            {"reaction_time": timedelta(hours=2)},
            0,
            [(0, 0)],
        ),
        # A device that cannot move in any direction gets react 0 either.
        (
            {"reaction_directions": ["consumption-down"]},
            0,
            [(0, 0)],
        ),
    ],
)
def test_reaction_directions_and_time_gate_the_band_and_react(
    app, db, internal_keys, expected_react, expected_band
):
    """The internal reaction directions cut the band to the directions the device can move in, and a slow device gets react 0.

    A negative production price makes every slot a reacting slot, and idling the battery's unique optimum.
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name=f"Recourse site (reaction {sorted(internal_keys.items())})",
        consumption_prices="50 EUR/MWh",
        production_prices="-1 EUR/MWh",
        load_kw=None,
    )
    data = _compute_recourse(
        site,
        battery_power,
        load_sensor,
        price_fields,
        end,
        site_power_capacity="100 kW",
        internal_device_keys={0: internal_keys},
    )[battery_power.id]["data"]
    # With nothing to gain from charging or discharging, the battery idles.
    np.testing.assert_allclose(data["p"], 0, atol=TOLERANCE)
    np.testing.assert_allclose(data["react"], expected_react)
    np.testing.assert_allclose(data["band"].iloc[0], expected_band, atol=TOLERANCE)


def test_device_without_react_gets_no_share(app, db):
    """Only devices with ``react`` set react; a second battery without it keeps react 0 and a band of its plan."""
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (react per device)",
        consumption_prices="50 EUR/MWh",
        production_prices="0 EUR/MWh",
        load_kw=None,
    )
    other_battery = (
        db.session.query(Sensor)
        .filter_by(name="other battery power", generic_asset=site)
        .one_or_none()
    )
    if other_battery is None:
        other_battery = Sensor(
            name="other battery power",
            generic_asset=site,
            unit="MW",
            event_resolution=RESOLUTION,
        )
        db.session.add(other_battery)
        db.session.commit()

    rules = _compute_recourse(
        site,
        battery_power,
        load_sensor,
        price_fields,
        end,
        site_power_capacity="100 kW",
        flex_model=[
            _battery_flex_model(battery_power),
            _battery_flex_model(other_battery, react=False),
        ],
    )
    np.testing.assert_allclose(rules[battery_power.id]["data"]["react"], 1)
    np.testing.assert_allclose(rules[other_battery.id]["data"]["react"], 0)
    _assert_bands_are_well_formed(rules[other_battery.id]["data"])


@pytest.mark.parametrize("retrigger", [None, False])
def test_retrigger_flag_defaults_to_true(app, db, retrigger):
    """Each rule entry carries the retrigger flag, true unless the internal flex-context key says otherwise."""
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name=f"Recourse site (retrigger {retrigger})",
        consumption_prices="50 EUR/MWh",
        production_prices="0 EUR/MWh",
        load_kw=None,
    )
    rule = _compute_recourse(
        site,
        battery_power,
        load_sensor,
        price_fields,
        end,
        site_power_capacity="100 kW",
        internal_context_keys=(
            {} if retrigger is None else {"retrigger_on_band_exit": retrigger}
        ),
    )[battery_power.id]
    assert rule["retrigger_on_band_exit"] is (True if retrigger is None else retrigger)


def test_no_reaction_rules_without_the_opt_in(app, db):
    """Without a device setting ``react``, the scheduler returns no reaction rules."""
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (no opt-in)",
        consumption_prices="50 EUR/MWh",
        production_prices="0 EUR/MWh",
        load_kw=None,
    )
    scheduler = StorageScheduler(
        asset_or_sensor=site,
        start=START,
        end=end,
        resolution=RESOLUTION,
        belief_time=START,
        flex_model=[_battery_flex_model(battery_power, react=False)],
        flex_context={**price_fields, "site-power-capacity": "100 kW"},
        return_multiple=True,
    )
    results = scheduler.compute()
    assert not [r for r in results if r["name"] == "recourse_rule"]
