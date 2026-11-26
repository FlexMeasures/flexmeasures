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
    flex_context_extra: dict | None = None,
    internal_device_keys: dict[int, dict] | None = None,
    internal_context_keys: dict | None = None,
) -> dict[int, pd.DataFrame]:
    """Schedule the site and return each device's reaction rule data by sensor ID.

    ``flex_context_extra`` adds public flex-context fields.
    ``internal_device_keys`` (by device index) and ``internal_context_keys`` are set on the deserialized flex config,
    the way the scheduler reads keys the public schemas do not expose yet.
    """
    if flex_model is None:
        flex_model = [_battery_flex_model(battery_power)]
    flex_context = {
        **price_fields,
        "site-power-capacity": site_power_capacity,
        **(flex_context_extra or {}),
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
    assert len(rules) == sum(1 for fm in flex_model if fm.get("react"))
    return {rule["sensor"].id: rule for rule in rules}


def _clip_to_band(
    value: float, band: list[tuple[float, float]], current: float | None = None
) -> float:
    """The client rule for a band of several ranges: a value inside a range is returned as is,
    a value beyond the band's ends is clipped to the nearest end,
    and a value in a hole between two ranges is rounded to the edge on the side of the device's current mode,
    which is the range holding ``current`` (the plan, at the start of a slot).
    """
    if any(lo <= value <= hi for lo, hi in band):
        return value
    if value < band[0][0]:
        return band[0][0]
    if value > band[-1][1]:
        return band[-1][1]
    current = value if current is None else current
    for (_, previous_hi), (next_lo, _) in zip(band, band[1:]):
        if previous_hi < value < next_lo:
            return previous_hi if current <= previous_hi else next_lo
    raise AssertionError("a value is either in a range, beyond an end, or in a hole")


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
        assert np.isclose(
            _clip_to_band(row["p"], band, row["p"]), row["p"], atol=TOLERANCE
        )
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
    - react: the site capacity binds at the optimum in slots 0 and 2 (net flow exactly 15, the capacity kink), so the battery gets 1 there and 0 elsewhere;
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

    That holds when the reference is the uncontrolled forecast (so the deviation from the balance point is zero) and the band contains the plan.
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
                row["p"],
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


MODES_IDLE_OR_1_4_TO_2_KW = [
    {"consumption-range": ["0 kW", "0 kW"]},
    {"consumption-range": ["1.4 kW", "2 kW"]},
    {"production-range": ["1.4 kW", "2 kW"]},
]


def _mode_battery(sensor: Sensor, **extra) -> dict:
    """A battery that is idle, or charges or discharges between 1.4 and 2 kW, starting empty."""
    return _battery_flex_model(
        sensor,
        **{
            "power-capacity": "2 kW",
            "soc-at-start": "0 MWh",
            "operation-modes": MODES_IDLE_OR_1_4_TO_2_KW,
            **extra,
        },
    )


def test_mode_shaped_plan_is_balanced_at_its_miss(app, db):
    """A plan that operation modes keep 0.2 kW off zero still reacts, against the balance point rather than the forecast.

    Two hourly slots. In the first, 1.2 kW of surplus sun meets a feed-in price (5) below the import price (50):
    the battery charges its smallest step of 1.4 kW to store the sun for the second slot,
    where a 1.4 kW load at an import price of 100 is served from the battery.
    The planned connection power in the first slot is +0.2 kW, within the 1.4 kW gap between idle and the charging range,
    so the slot is held at zero: the reference is -1.4 kW (the negative of the plan), react is 1,
    and the band lists idle and the charging range [1.4, 2] kW.
    Applying the client rule, 0.3 kW of extra sun gives a setpoint of 1.5 kW,
    and the house as forecast gives a raw value of 1.2 kW in the hole, rounded to the plan's side: exactly the plan.
    In the second slot the battery empties itself, so its discharging range is a point, but idling or charging stay feasible,
    so it still reacts, against the forecast (the plan sits on the balancing power).
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (mode-shaped plan)",
        consumption_prices=[50, 100],
        production_prices=[5, 5],
        load_kw=[-1.2, 1.4],
        n_hours=2,
    )
    data = _compute_recourse(
        site,
        battery_power,
        load_sensor,
        price_fields,
        end,
        site_power_capacity="100 kW",
        flex_model=[_mode_battery(battery_power)],
    )[battery_power.id]["data"]

    np.testing.assert_allclose(
        data["p"], [0.0014, -0.0014], atol=TOLERANCE, err_msg="plan"
    )
    np.testing.assert_allclose(data["react"], [1, 1], err_msg="react")
    np.testing.assert_allclose(
        data["reference"], [-0.0014, 0.0014], atol=TOLERANCE, err_msg="balance point"
    )
    np.testing.assert_allclose(
        data["band"].iloc[0], [(0, 0), (0.0014, 0.002)], atol=TOLERANCE
    )
    np.testing.assert_allclose(
        data["band"].iloc[1],
        [(-0.0014, -0.0014), (0, 0), (0.0014, 0.002)],
        atol=TOLERANCE,
    )

    p, react, reference, band = (
        data.iloc[0][key] for key in ("p", "react", "reference", "band")
    )
    house_as_forecast = -0.0012
    assert _clip_to_band(p - react * (house_as_forecast - reference), band, p) == p
    extra_sun = -0.0015
    assert _clip_to_band(p - react * (extra_sun - reference), band, p) == pytest.approx(
        0.0015, abs=TOLERANCE
    )


def test_miss_beyond_the_dead_zone_is_not_classified(app, db):
    """A device at its capacity while the house still exports cannot reach the price kink, so it does not react.

    With 5 kW of surplus sun, the battery charges its full 2 kW to serve the second slot's load,
    leaving 3 kW of export: balancing the connection would take 5 kW, beyond the device's 2 kW reach,
    so the reference is the forecast and the band is just the plan.
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (miss beyond the dead zone)",
        consumption_prices=[50, 100],
        production_prices=[5, 5],
        load_kw=[-5, 2],
        n_hours=2,
    )
    data = _compute_recourse(
        site,
        battery_power,
        load_sensor,
        price_fields,
        end,
        site_power_capacity="100 kW",
        flex_model=[_mode_battery(battery_power)],
    )[battery_power.id]["data"]
    np.testing.assert_allclose(data["p"].iloc[0], 0.002, atol=TOLERANCE, err_msg="plan")
    assert data["react"].iloc[0] == 0
    np.testing.assert_allclose(
        data["reference"].iloc[0], -0.005, atol=TOLERANCE, err_msg="forecast"
    )
    np.testing.assert_allclose(data["band"].iloc[0], [(0.002, 0.002)], atol=TOLERANCE)


def _charger(sensor: Sensor, **extra) -> dict:
    """A charger that is idle or charges between 1.4 and 7.4 kW, starting empty, with room for 30 kWh."""
    return _battery_flex_model(
        sensor,
        **{
            "power-capacity": "7.4 kW",
            "soc-at-start": "0 MWh",
            "soc-max": "0.03 MWh",
            "operation-modes": [
                {"consumption-range": ["0 kW", "0 kW"]},
                {"consumption-range": ["1.4 kW", "7.4 kW"]},
            ],
            **extra,
        },
    )


def test_clouds_where_sun_was_planned_with_a_target_this_evening(app, db):
    """A planned deviation from the balance point keeps the forecast as reference, and the kink within reach gives react 1.

    A charger (idle or 1.4 to 7.4 kW) meets 4.4 kW of surplus sun in each of four hourly slots, with feed-in below import,
    and must hold 21.2 kWh by the evening. Import gets cheaper over the day, so the plan absorbs the sun (4.4 kW) in the first
    two slots and imports the missing 3.6 kWh as late as it can: 5.0 kW in the third slot and the full 7.4 kW in the fourth.
    The balancing power (4.4 kW) lies inside the charging range in every slot, so the plan's misses are deliberate, not mode-shaped,
    and the reference stays the forecast of -4.4 kW. The band lists every feasible range: idle and the charging range at first,
    then only the charging range with its lower bound rising as the (hard) target comes within reach,
    and in the last slot a single point, so the charger does not react there.
    In the third slot, 1 kW of extra sun must be absorbed on top of the planned import: the client rule gives 6.0 kW.
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (clouds and a target)",
        consumption_prices=[50, 49, 48, 47],
        production_prices=[5, 5, 5, 5],
        load_kw=[-4.4, -4.4, -4.4, -4.4],
    )
    data = _compute_recourse(
        site,
        battery_power,
        load_sensor,
        price_fields,
        end,
        site_power_capacity="100 kW",
        flex_model=[
            _charger(
                battery_power,
                **{
                    "soc-targets": [
                        {"datetime": end.isoformat(), "value": "0.0212 MWh"}
                    ]
                },
            )
        ],
        # A hard target, so that its reachability narrows the band.
        flex_context_extra={"relax-soc-constraints": False},
    )[battery_power.id]["data"]

    np.testing.assert_allclose(
        data["p"], [0.0044, 0.0044, 0.0050, 0.0074], atol=TOLERANCE, err_msg="plan"
    )
    np.testing.assert_allclose(data["react"], [1, 1, 1, 0], err_msg="react")
    np.testing.assert_allclose(
        data["reference"], -0.0044, atol=TOLERANCE, err_msg="forecast"
    )
    expected_bands = [
        [(0, 0), (0.0014, 0.0074)],
        [(0.0020, 0.0074)],
        [(0.0050, 0.0074)],
        [(0.0074, 0.0074)],
    ]
    for band, expected in zip(data["band"], expected_bands):
        np.testing.assert_allclose(band, expected, atol=TOLERANCE)

    p, react, reference, band = (
        data.iloc[2][key] for key in ("p", "react", "reference", "band")
    )
    extra_sun = -0.0054
    assert _clip_to_band(p - react * (extra_sun - reference), band, p) == pytest.approx(
        0.0060, abs=TOLERANCE
    )
    assert _clip_to_band(p - react * (-0.0044 - reference), band, p) == p


def test_negative_feed_in_without_a_forecast(app, db):
    """Without any uncontrolled device the reference is 0.0, and a negative feed-in price makes the charger react
    even though the plan does not hold the connection at zero.

    Paid to consume, the charger fills its 4.4 kWh in the first slot (4.4 kW, within its 1.4 to 7.4 kW range) and idles in the second,
    where its range is a point, so it does not react there.
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (negative feed-in, no forecast)",
        consumption_prices="-10 EUR/MWh",
        production_prices="-10 EUR/MWh",
        load_kw=None,
        n_hours=2,
    )
    data = _compute_recourse(
        site,
        battery_power,
        load_sensor,
        price_fields,
        end,
        site_power_capacity="100 kW",
        flex_model=[_charger(battery_power, **{"soc-max": "0.0044 MWh"})],
    )[battery_power.id]["data"]
    np.testing.assert_allclose(data["p"], [0.0044, 0], atol=TOLERANCE, err_msg="plan")
    np.testing.assert_allclose(data["react"], [1, 0], err_msg="react")
    np.testing.assert_allclose(
        data["reference"], [0.0, 0.0], atol=TOLERANCE, err_msg="reference"
    )
    np.testing.assert_allclose(
        data["band"].iloc[0], [(0, 0), (0.0014, 0.0044)], atol=TOLERANCE
    )
    np.testing.assert_allclose(data["band"].iloc[1], [(0, 0)], atol=TOLERANCE)


@pytest.mark.parametrize(
    ["soc_maxima", "expected_react", "expected_band"],
    [
        # Room to charge: idle and the charging range are feasible, and the idle plan reacts against the balance point 0.0.
        (None, 1, [(0, 0), (0.0014, 0.0074)]),
        # A soft soc-maxima that charging would breach within the slot empties the charging range: a one-point band, no reaction.
        ("0.001 MWh", 0, [(0, 0)]),
    ],
)
def test_idle_plan_with_a_surplus(app, db, soc_maxima, expected_react, expected_band):
    """An idle charger facing 1.2 kW of surplus reacts when it has room to charge, against a balance point of 0.0.

    Storing the surplus would take the charger's smallest step of 1.4 kW, importing 0.2 kW at 50 instead of exporting 1.2 kW at 5,
    and the stored energy has no later use, so the plan idles: the balancing power (1.2 kW) falls in the hole between idle and charging,
    with the plan at its lower edge, so the reference is 0.0 rather than the -1.2 kW forecast.
    Applying the client rule, 0.5 kW of extra sun gives a raw value of 1.7 kW inside the charging range, and the house as forecast
    gives 1.2 kW in the hole, rounded to the plan's side: idle.
    The soc-maxima is left soft (the default relaxation), yet it narrows the band like a hard limit.
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name=f"Recourse site (idle plan, soc-maxima {soc_maxima})",
        consumption_prices="50 EUR/MWh",
        production_prices="5 EUR/MWh",
        load_kw=-1.2,
        n_hours=1,
    )
    data = _compute_recourse(
        site,
        battery_power,
        load_sensor,
        price_fields,
        end,
        site_power_capacity="100 kW",
        flex_model=[
            _charger(
                battery_power,
                **({} if soc_maxima is None else {"soc-maxima": soc_maxima}),
            )
        ],
    )[battery_power.id]["data"]
    row = data.iloc[0]
    np.testing.assert_allclose(row["p"], 0, atol=TOLERANCE, err_msg="plan")
    assert row["react"] == expected_react
    np.testing.assert_allclose(row["band"], expected_band, atol=TOLERANCE)
    if expected_react:
        np.testing.assert_allclose(row["reference"], 0.0, atol=TOLERANCE)
        extra_sun = -0.0017
        assert _clip_to_band(
            row["p"] - row["react"] * (extra_sun - row["reference"]),
            row["band"],
            row["p"],
        ) == pytest.approx(0.0017, abs=TOLERANCE)
        house_as_forecast = -0.0012
        assert (
            _clip_to_band(
                row["p"] - row["react"] * (house_as_forecast - row["reference"]),
                row["band"],
                row["p"],
            )
            == 0
        )
    else:
        np.testing.assert_allclose(row["reference"], -0.0012, atol=TOLERANCE)


def test_plan_just_below_the_fuse_holds_the_price_kink(app, db):
    """A plan that the modes keep less than a step below the fuse is not at the capacity kink; it holds the price kink.

    A one-phase connection of 5.75 kW, 2 kW of surplus sun, feed-in below import, and a charger (idle or 1.4 to 7.4 kW)
    that must hold 13 kWh after two hours. Import is cheaper in the first hour, so the charger takes its full 7.4 kW then
    (importing 5.4 kW, 0.35 kW below the fuse) and the remaining 5.6 kW in the second hour.
    Balancing the connection at the fuse would take 7.75 kW, beyond the charger's reach, but balancing it at zero takes 2 kW:
    the first slot reacts at the price kink, against the forecast, with every range the target leaves feasible.
    The second slot's range is pinned by the target, so it does not react.
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (just below the fuse)",
        consumption_prices=[49, 50],
        production_prices=[5, 5],
        load_kw=[-2, -2],
        n_hours=2,
    )
    data = _compute_recourse(
        site,
        battery_power,
        load_sensor,
        price_fields,
        end,
        site_power_capacity="5.75 kW",
        flex_model=[
            _charger(
                battery_power,
                **{
                    "soc-targets": [{"datetime": end.isoformat(), "value": "0.013 MWh"}]
                },
            )
        ],
        flex_context_extra={"relax-soc-constraints": False},
    )[battery_power.id]["data"]
    np.testing.assert_allclose(
        data["p"], [0.0074, 0.0056], atol=TOLERANCE, err_msg="plan"
    )
    np.testing.assert_allclose(data["react"], [1, 0], err_msg="react")
    np.testing.assert_allclose(
        data["reference"], -0.002, atol=TOLERANCE, err_msg="forecast"
    )
    np.testing.assert_allclose(data["band"].iloc[0], [(0.0056, 0.0074)], atol=TOLERANCE)
    np.testing.assert_allclose(data["band"].iloc[1], [(0.0056, 0.0056)], atol=TOLERANCE)


def test_band_lists_every_feasible_range_within_its_modes(app, db):
    """A device with operation modes gets every range of its modes the plan leaves feasible, none spanning a hole.

    The battery can be off, consume between 2 and 5 kW, or produce between 2 and 5 kW;
    it serves a 3 kW load with the production price below the consumption price, so the connection is held at zero.
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (operation modes)",
        consumption_prices="50 EUR/MWh",
        production_prices="5 EUR/MWh",
        load_kw=3,
    )
    modes = [
        {"consumption-range": ["0 kW", "0 kW"]},
        {"consumption-range": ["2 kW", "5 kW"]},
        {"production-range": ["2 kW", "5 kW"]},
    ]
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
    # The battery serves the load until its 5 kWh run out: three hours at 3 kW is more than it holds.
    assert (data["p"] < -TOLERANCE).any()
    signed_modes = [(-0.005, -0.002), (0, 0), (0.002, 0.005)]
    for _, row in data.iterrows():
        if row["p"] < -TOLERANCE:
            assert row["react"] == 1
            np.testing.assert_allclose(row["reference"], 0.003, atol=TOLERANCE)
            assert len(row["band"]) >= 2, "idling stays feasible besides discharging"
            for lo, hi in row["band"]:
                assert any(
                    mode_lo - TOLERANCE <= lo and hi <= mode_hi + TOLERANCE
                    for mode_lo, mode_hi in signed_modes
                ), f"range ({lo}, {hi}) spans a hole between the operation modes"


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


def test_device_without_react_gets_no_rules(app, db):
    """Only devices with ``react`` set get reaction rules; a second battery without it gets none at all.

    A negative production price makes idling the batteries' unique optimum, with the connection held at zero.
    """
    site, battery_power, load_sensor, price_fields, end = _build_site(
        db,
        site_name="Recourse site (react per device)",
        consumption_prices="50 EUR/MWh",
        production_prices="-1 EUR/MWh",
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
    assert other_battery.id not in rules


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
