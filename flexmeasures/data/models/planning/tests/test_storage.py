from datetime import datetime, timedelta

import pytz

import numpy as np
import pandas as pd

from flexmeasures.data.models.planning import Scheduler
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.data.models.planning.utils import initialize_index
from flexmeasures.data.models.planning.tests.utils import (
    check_constraints,
    get_sensors_from_db,
    series_to_ts_specs,
)
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.scheduling_result import SchedulingJobResult


def test_battery_solver_multi_commitment(add_battery_assets, db):
    _, battery = get_sensors_from_db(
        db, add_battery_assets, battery_name="Test battery"
    )
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 1))
    end = tz.localize(datetime(2015, 1, 2))
    resolution = timedelta(minutes=15)
    soc_at_start = 0.4
    index = initialize_index(start=start, end=end, resolution=resolution)
    production_prices = pd.Series(90, index=index)
    consumption_prices = pd.Series(100, index=index)
    scheduler: Scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={
            "soc-at-start": f"{soc_at_start} MWh",
            "soc-min": "0 MWh",
            "soc-max": "1 MWh",
            "power-capacity": "1 MVA",
            "soc-minima": [
                {
                    "datetime": "2015-01-02T00:00:00+01:00",
                    "value": "1 MWh",
                }
            ],
            "prefer-charging-sooner": False,
        },
        flex_context={
            "consumption-price": series_to_ts_specs(consumption_prices, unit="EUR/MWh"),
            "production-price": series_to_ts_specs(production_prices, unit="EUR/MWh"),
            "site-power-capacity": "2 MW",  # should be big enough to avoid any infeasibilities
            "site-consumption-capacity": "1 kW",  # we'll need to breach this to reach the target
            "site-consumption-breach-price": "1000 EUR/kW",
            "site-production-breach-price": "1000 EUR/kW",
            "site-peak-consumption": "20 kW",
            "site-peak-production": "20 kW",
            "site-peak-consumption-price": "260 EUR/MW",
            # Cheap commitments that are not expected to affect the resulting schedule
            "commitments": [
                {
                    "name": "a sample commitment penalizing peaks",
                    "baseline": [
                        {
                            "value": "0 kW",
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                        }
                    ],
                    "up-price": "1 EUR/MW",
                    "down-price": [
                        {
                            "value": "-1 EUR/MW",
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                        }
                    ],
                },
                {
                    "name": "a sample commitment penalizing demand/supply",
                    # "baseline": "0 kW",  # commented out to check defaulting to 0 also works
                    "up-price": "1 EUR/MWh",
                    "down-price": "-1 EUR/MWh",
                },
            ],
            # The following is a constant price, but this checks currency conversion in case a later price field is
            # set to a time series specs (i.e. a list of dicts, where each dict represents a time slot)
            "site-peak-production-price": series_to_ts_specs(
                pd.Series(260, production_prices.index), unit="EUR/MW"
            ),
            "soc-minima-breach-price": "6000 EUR/kWh",  # high breach price (to mimic a hard constraint)
        },
        return_multiple=True,
    )
    results = scheduler.compute()

    schedule = results[0]["data"]
    costs = results[1]["data"]
    costs_unit = results[1]["unit"]
    assert costs_unit == "EUR"

    # Check if constraints were met
    check_constraints(battery, schedule, soc_at_start)

    # Check for constant charging profile (minimizing the consumption breach)
    np.testing.assert_allclose(schedule, (1 - 0.4) / 24)

    # Check costs are correct
    # 60 EUR for 600 kWh consumption priced at 100 EUR/MWh
    np.testing.assert_almost_equal(costs["energy"], 100 * (1 - 0.4))
    # 24000 EUR for any 24 kW consumption breach priced at 1000 EUR/kW
    np.testing.assert_almost_equal(costs["any consumption breach"], 1000 * (25 - 1))
    # 24000 EUR for each 24 kW consumption breach per hour priced at 1000 EUR/kWh
    np.testing.assert_almost_equal(
        costs["all consumption breaches"], 1000 * (25 - 1) * 96 / 4
    )
    # No production breaches
    np.testing.assert_almost_equal(costs["any production breach"], 0)
    np.testing.assert_almost_equal(costs["all production breaches"], 0 * 96)
    # 1.3 EUR for the 5 kW extra consumption peak priced at 260 EUR/MW
    np.testing.assert_almost_equal(costs["consumption peak"], 260 / 1000 * (25 - 20))
    # No production peak
    np.testing.assert_almost_equal(costs["production peak"], 0)

    # Sample commitments
    np.testing.assert_almost_equal(
        costs["a sample commitment penalizing peaks"], 4 * (1 - 0.4)
    )
    np.testing.assert_almost_equal(
        costs["a sample commitment penalizing demand/supply"], 1 * (1 - 0.4)
    )


def test_battery_relaxation(add_battery_assets, db):
    """Check that resolving SoC breaches is more important than resolving device power breaches.

    The battery is still charging with 25 kW between noon and 4 PM, when the consumption capacity is supposed to be 0.
    It is still charging because resolving the still unmatched SoC minima takes precedence (via breach prices).
    """
    _, battery = get_sensors_from_db(
        db, add_battery_assets, battery_name="Test battery"
    )
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 1))
    end = tz.localize(datetime(2015, 1, 2))
    resolution = timedelta(minutes=15)
    soc_at_start = 0.4
    index = initialize_index(start=start, end=end, resolution=resolution)
    consumption_prices = pd.Series(100, index=index)
    # Introduce arbitrage opportunity
    consumption_prices["2015-01-01T16:00:00+01:00":"2015-01-01T17:00:00+01:00"] = (
        0  # cheap energy
    )
    consumption_prices["2015-01-01T17:00:00+01:00":"2015-01-01T18:00:00+01:00"] = (
        1000  # expensive energy
    )
    production_prices = consumption_prices - 10
    device_power_breach_price = 100

    # Set up consumption/production capacity as a time series
    # i.e. it takes 16 hours to go from 0.4 to 0.8 MWh
    consumption_capacity_in_mw = 0.025
    consumption_capacity = pd.Series(consumption_capacity_in_mw, index=index)
    consumption_capacity["2015-01-01T12:00:00+01:00":"2015-01-01T18:00:00+01:00"] = (
        0  # no charging
    )
    production_capacity = consumption_capacity

    scheduler: Scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={
            "soc-at-start": f"{soc_at_start} MWh",
            "soc-min": "0 MWh",
            "soc-max": "1 MWh",
            "power-capacity": f"{consumption_capacity_in_mw} MVA",
            "consumption-capacity": series_to_ts_specs(consumption_capacity, unit="MW"),
            "production-capacity": series_to_ts_specs(production_capacity, unit="MW"),
            "soc-minima": [
                {
                    "start": "2015-01-01T12:00:00+01:00",
                    "duration": "PT6H",
                    "value": "0.8 MWh",
                }
            ],
            "prefer-charging-sooner": False,
        },
        flex_context={
            "consumption-price": series_to_ts_specs(consumption_prices, unit="EUR/MWh"),
            "production-price": series_to_ts_specs(production_prices, unit="EUR/MWh"),
            "site-power-capacity": "2 MW",  # should be big enough to avoid any infeasibilities
            # "site-consumption-capacity": "1 kW",  # we'll need to breach this to reach the target
            "site-consumption-breach-price": "1000 EUR/kW",
            "site-production-breach-price": "1000 EUR/kW",
            "site-peak-consumption": "20 kW",
            "site-peak-production": "20 kW",
            "site-peak-consumption-price": [
                {
                    "start": start.isoformat(),
                    "duration": "PT2H",
                    "value": "260 EUR/MW",
                },
                {
                    "start": (start + timedelta(hours=2)).isoformat(),
                    "duration": "PT22H",
                    "value": "235 EUR/MW",
                },
            ],
            # The following is a constant price, but this checks currency conversion in case a later price field is
            # set to a time series specs (i.e. a list of dicts, where each dict represents a time slot)
            "site-peak-production-price": series_to_ts_specs(
                pd.Series(260, production_prices.index), unit="EUR/MW"
            ),
            "soc-minima-breach-price": "6000 EUR/kWh",  # high breach price (to mimic a hard constraint)
            "consumption-breach-price": f"{device_power_breach_price} EUR/kW",  # lower breach price (thus prioritizing minimizing soc breaches)
            "production-breach-price": f"{device_power_breach_price} EUR/kW",  # lower breach price (thus prioritizing minimizing soc breaches)
        },
        return_multiple=True,
    )
    results = scheduler.compute()

    schedule = results[0]["data"]
    costs = results[1]["data"]
    costs_unit = results[1]["unit"]
    assert costs_unit == "EUR"

    # Check if constraints were met
    check_constraints(battery, schedule, soc_at_start)

    # Check for constant charging profile until 4 PM (thus breaching the consumption capacity after noon)
    np.testing.assert_allclose(
        schedule[:"2015-01-01T15:45:00+01:00"], consumption_capacity_in_mw
    )

    # Check for standing idle from 4 PM to 6 PM
    np.testing.assert_allclose(
        schedule["2015-01-01T16:00:00+01:00":"2015-01-01T17:45:00+01:00"], 0
    )

    # Check costs are correct
    np.testing.assert_almost_equal(
        costs["any consumption breach device 0"],
        device_power_breach_price * consumption_capacity_in_mw * 1000,
    )  # 100 EUR/kW * 0.025 MW * 1000 kW/MW

    np.testing.assert_almost_equal(
        costs["all consumption breaches device 0"],
        device_power_breach_price * consumption_capacity_in_mw * 1000 * 4,
    )  # 100 EUR/(kW*h) * 0.025 MW * 1000 kW/MW * 4 hours


def test_unresolved_targets_soc_minima(add_battery_assets, db):
    """Test that unresolved soc-minima targets are reported in the scheduling result.

    A battery starts at 0.4 MWh with a very limited charging capacity (0.01 MW).
    With 100% efficiency and 24 hours, it can gain at most 0.01 * 24 = 0.24 MWh,
    reaching a max SoC of ~0.64 MWh.  No roundtrip or storage efficiency is set,
    so the default (100%) applies.
    A soc-minima of 0.9 MWh is set as a soft constraint (via a breach price).
    The scheduler will charge at full capacity but still fail to reach the target,
    so the scheduling result should report an unresolved soc-minima.
    """
    _, battery = get_sensors_from_db(
        db, add_battery_assets, battery_name="Test battery"
    )
    soc_sensor = Sensor(
        name="state-of-charge-minima-test",
        generic_asset=battery.generic_asset,
        unit="MWh",
        event_resolution=timedelta(0),
    )
    db.session.add(soc_sensor)
    db.session.flush()

    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 1))
    end = tz.localize(datetime(2015, 1, 2))
    resolution = timedelta(minutes=15)
    soc_at_start = 0.4
    index = initialize_index(start=start, end=end, resolution=resolution)
    consumption_prices = pd.Series(100, index=index)

    scheduler: Scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={
            "soc-at-start": f"{soc_at_start} MWh",
            "soc-min": "0 MWh",
            "soc-max": "1 MWh",
            "power-capacity": "0.01 MVA",  # very limited: max gain 0.24 MWh over 24 h
            "soc-minima": [
                {
                    "datetime": "2015-01-02T00:00:00+01:00",
                    "value": "0.9 MWh",  # unreachable
                }
            ],
            "state-of-charge": {"sensor": soc_sensor.id},
            "prefer-charging-sooner": False,
        },
        flex_context={
            "consumption-price": series_to_ts_specs(consumption_prices, unit="EUR/MWh"),
            "production-price": series_to_ts_specs(consumption_prices, unit="EUR/MWh"),
            "site-power-capacity": "2 MW",
            "soc-minima-breach-price": "1 EUR/kWh",  # soft constraint
        },
        return_multiple=True,
    )
    results = scheduler.compute()

    # The scheduling_result entry should be present
    scheduling_result_entry = next(
        (r for r in results if r.get("name") == "scheduling_result"), None
    )
    assert scheduling_result_entry is not None

    scheduling_result = scheduling_result_entry["data"]
    assert isinstance(scheduling_result, SchedulingJobResult)

    unresolved_targets = scheduling_result.unresolved_targets
    assert (
        str(soc_sensor.id) in unresolved_targets
    ), "Expected an unresolved soc-minima since the target is unreachable"
    assert "soc-minima" in unresolved_targets[str(soc_sensor.id)]
    # The scheduled SoC should be below the 0.9 MWh target (unmet == 260.0 kWh shortage)
    assert unresolved_targets[str(soc_sensor.id)]["soc-minima"]["unmet"] == "260.0 kWh"
    # The constraint is at 2015-01-02T00:00:00+01:00 = 2015-01-01T23:00:00+00:00 (UTC)
    assert (
        unresolved_targets[str(soc_sensor.id)]["soc-minima"]["datetime"]
        == "2015-01-01T23:00:00+00:00"
    )

    # No soc-maxima was set, so it should not appear
    assert "soc-maxima" not in unresolved_targets[str(soc_sensor.id)]

    # No soc-maxima constraint defined, so resolved_targets should be empty
    assert scheduling_result.resolved_targets == {}


def test_unresolved_targets_none_when_met(add_battery_assets, db):
    """Test that no unresolved targets are reported when constraints are fully met.

    A battery starts at 0.4 MWh and has a soc-minima of 0.5 MWh at end of schedule.
    With enough capacity, the scheduler can easily charge to 0.5 MWh, so the
    scheduling result should have no unresolved soc-minima.
    """
    _, battery = get_sensors_from_db(
        db, add_battery_assets, battery_name="Test battery"
    )
    soc_sensor = Sensor(
        name="state-of-charge-none-when-met-test",
        generic_asset=battery.generic_asset,
        unit="MWh",
        event_resolution=timedelta(0),
    )
    db.session.add(soc_sensor)
    db.session.flush()

    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 1))
    end = tz.localize(datetime(2015, 1, 2))
    resolution = timedelta(minutes=15)
    soc_at_start = 0.4
    index = initialize_index(start=start, end=end, resolution=resolution)
    consumption_prices = pd.Series(100, index=index)

    scheduler: Scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={
            "soc-at-start": f"{soc_at_start} MWh",
            "soc-min": "0 MWh",
            "soc-max": "1 MWh",
            "power-capacity": "2 MVA",  # plenty of capacity to reach 0.5 MWh
            "soc-minima": [
                {
                    "datetime": "2015-01-02T00:00:00+01:00",
                    "value": "0.5 MWh",  # easily reachable
                }
            ],
            "state-of-charge": {"sensor": soc_sensor.id},
            "prefer-charging-sooner": False,
        },
        flex_context={
            "consumption-price": series_to_ts_specs(consumption_prices, unit="EUR/MWh"),
            "production-price": series_to_ts_specs(consumption_prices, unit="EUR/MWh"),
            "site-power-capacity": "2 MW",
            "soc-minima-breach-price": "1 EUR/kWh",  # soft constraint
        },
        return_multiple=True,
    )
    results = scheduler.compute()

    scheduling_result_entry = next(
        (r for r in results if r.get("name") == "scheduling_result"), None
    )
    assert scheduling_result_entry is not None
    scheduling_result = scheduling_result_entry["data"]
    unresolved_targets = scheduling_result.unresolved_targets
    # The minima target is met, so no unresolved targets expected
    assert unresolved_targets == {}

    # The soc-minima was met, so resolved_targets should report it
    assert str(soc_sensor.id) in scheduling_result.resolved_targets
    assert "soc-minima" in scheduling_result.resolved_targets[str(soc_sensor.id)]
    margin_str = scheduling_result.resolved_targets[str(soc_sensor.id)]["soc-minima"][
        "margin"
    ]
    # Margin should be a non-negative kWh string
    assert margin_str.endswith(" kWh")
    assert float(margin_str.replace(" kWh", "")) >= 0


def test_unresolved_targets_soc_maxima(add_battery_assets, db):
    """Test that unresolved soc-maxima targets are reported in the scheduling result.

    A battery starts at 0.9 MWh with a very limited discharge capacity (0.01 MW).
    With 100% efficiency and 24 hours, it can discharge at most 0.01 * 24 = 0.24 MWh,
    reaching a min SoC of ~0.66 MWh.  No roundtrip or storage efficiency is set,
    so the default (100%) applies.
    A soc-maxima of 0.5 MWh is set as a soft constraint (via a breach price).
    The scheduler will discharge at full capacity but still remain above the target,
    so the scheduling result should report an unresolved soc-maxima.
    """
    _, battery = get_sensors_from_db(
        db, add_battery_assets, battery_name="Test battery"
    )
    soc_sensor = Sensor(
        name="state-of-charge-maxima-test",
        generic_asset=battery.generic_asset,
        unit="MWh",
        event_resolution=timedelta(0),
    )
    db.session.add(soc_sensor)
    db.session.flush()

    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 1))
    end = tz.localize(datetime(2015, 1, 2))
    resolution = timedelta(minutes=15)
    soc_at_start = 0.9
    index = initialize_index(start=start, end=end, resolution=resolution)
    consumption_prices = pd.Series(100, index=index)

    scheduler: Scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={
            "soc-at-start": f"{soc_at_start} MWh",
            "soc-min": "0 MWh",
            "soc-max": "1 MWh",
            "power-capacity": "0.01 MVA",  # very limited: max discharge 0.24 MWh over 24 h
            "soc-maxima": [
                {
                    "datetime": "2015-01-02T00:00:00+01:00",
                    "value": "0.5 MWh",  # unreachably low
                }
            ],
            "state-of-charge": {"sensor": soc_sensor.id},
            "prefer-charging-sooner": False,
        },
        flex_context={
            "consumption-price": series_to_ts_specs(consumption_prices, unit="EUR/MWh"),
            "production-price": series_to_ts_specs(consumption_prices, unit="EUR/MWh"),
            "site-power-capacity": "2 MW",
            "soc-maxima-breach-price": "1 EUR/kWh",  # soft constraint
        },
        return_multiple=True,
    )
    results = scheduler.compute()

    scheduling_result_entry = next(
        (r for r in results if r.get("name") == "scheduling_result"), None
    )
    assert scheduling_result_entry is not None

    unresolved_targets = scheduling_result_entry["data"].unresolved_targets
    assert (
        str(soc_sensor.id) in unresolved_targets
    ), "Expected an unresolved soc-maxima since the target is unreachable"
    assert "soc-maxima" in unresolved_targets[str(soc_sensor.id)]
    # The scheduled SoC should be above the 0.5 MWh target (unmet == 160.0 kWh excess)
    assert unresolved_targets[str(soc_sensor.id)]["soc-maxima"]["unmet"] == "160.0 kWh"
    # The constraint is at 2015-01-02T00:00:00+01:00 = 2015-01-01T23:00:00+00:00 (UTC)
    assert (
        unresolved_targets[str(soc_sensor.id)]["soc-maxima"]["datetime"]
        == "2015-01-01T23:00:00+00:00"
    )

    # No soc-minima was set, so it should not appear
    assert "soc-minima" not in unresolved_targets[str(soc_sensor.id)]

    # No soc-minima constraint defined, so resolved_targets should be empty
    assert scheduling_result_entry["data"].resolved_targets == {}
