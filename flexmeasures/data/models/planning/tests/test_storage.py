from datetime import datetime, timedelta
from unittest import mock

import pytz
import pytest

import numpy as np
import pandas as pd

from flexmeasures.data.models.planning import Scheduler
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.data.models.planning.utils import initialize_index
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.planning.tests.utils import (
    check_constraints,
    get_sensors_from_db,
    series_to_ts_specs,
)
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

    # Add consumption and production output sensors to the battery asset
    consumption_output_sensor = Sensor(
        name="consumption output",
        generic_asset=battery.generic_asset,
        unit="kW",
        event_resolution=resolution,
    )
    production_output_sensor = Sensor(
        name="production output",
        generic_asset=battery.generic_asset,
        unit="kW",
        event_resolution=resolution,
    )
    db.session.add(consumption_output_sensor)
    db.session.add(production_output_sensor)
    db.session.flush()

    scheduler: Scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={
            "soc-at-start": f"{soc_at_start} MWh",
            "soc-min": "0 MWh",
            "consumption": {"sensor": consumption_output_sensor.id},
            "production": {"sensor": production_output_sensor.id},
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

    # Check consumption/production output sensor schedules.
    # The battery charges at a constant rate (all positive values), so the consumption schedule
    # should match the power schedule in kW, and the production schedule should be all zeros.
    consumption_result = next(
        r for r in results if r.get("name") == "consumption_schedule"
    )
    production_result = next(
        r for r in results if r.get("name") == "production_schedule"
    )
    assert consumption_result["sensor"] is consumption_output_sensor
    assert consumption_result["unit"] == "kW"
    assert production_result["sensor"] is production_output_sensor
    assert production_result["unit"] == "kW"
    # Both sensors have the same resolution as the power sensor, so no resampling occurs.
    expected_kw = (1 - 0.4) / 24 * 1000  # MW -> kW
    np.testing.assert_allclose(consumption_result["data"], expected_kw)
    np.testing.assert_allclose(production_result["data"], 0)


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

    asset_id = battery.generic_asset.id
    unresolved = scheduling_result.unresolved
    entry = next((e for e in unresolved if e["asset"] == asset_id), None)
    assert (
        entry is not None
    ), "Expected an unresolved soc-minima since the target is unreachable"
    assert "soc-minima" in entry
    # Only a single soc-minima datetime was defined in the flex model, so the
    # violation list holds exactly one entry.
    assert len(entry["soc-minima"]) == 1
    # The scheduled SoC should be below the 0.9 MWh target (violation == 260.0 kWh shortage)
    assert entry["soc-minima"][0]["violation"] == "260.0 kWh"
    # The constraint is at 2015-01-02T00:00:00+01:00 = 2015-01-01T23:00:00+00:00 (UTC)
    assert entry["soc-minima"][0]["datetime"] == "2015-01-01T23:00:00+00:00"

    # No soc-maxima was set, so it should not appear
    assert "soc-maxima" not in entry

    # No soc-maxima constraint defined, so resolved should be empty
    assert scheduling_result.resolved == []


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
    asset_id = battery.generic_asset.id
    unresolved = scheduling_result.unresolved
    # The minima target is met, so no unresolved targets expected
    assert unresolved == []

    # The soc-minima was met, so resolved should report it
    entry = next(
        (e for e in scheduling_result.resolved if e["asset"] == asset_id), None
    )
    assert entry is not None
    assert "soc-minima" in entry
    # Only a single soc-minima datetime was defined in the flex model, so the
    # margin list holds exactly one entry.
    assert len(entry["soc-minima"]) == 1
    margin_str = entry["soc-minima"][0]["margin"]
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

    asset_id = battery.generic_asset.id
    unresolved = scheduling_result_entry["data"].unresolved
    entry = next((e for e in unresolved if e["asset"] == asset_id), None)
    assert (
        entry is not None
    ), "Expected an unresolved soc-maxima since the target is unreachable"
    assert "soc-maxima" in entry
    # Only a single soc-maxima datetime was defined in the flex model, so the
    # violation list holds exactly one entry.
    assert len(entry["soc-maxima"]) == 1
    # The scheduled SoC should be above the 0.5 MWh target (violation == 160.0 kWh excess)
    assert entry["soc-maxima"][0]["violation"] == "160.0 kWh"
    # The constraint is at 2015-01-02T00:00:00+01:00 = 2015-01-01T23:00:00+00:00 (UTC)
    assert entry["soc-maxima"][0]["datetime"] == "2015-01-01T23:00:00+00:00"

    # No soc-minima was set, so it should not appear
    assert "soc-minima" not in entry

    # No soc-minima constraint defined, so resolved should be empty
    assert scheduling_result_entry["data"].resolved == []


def test_unresolved_targets_no_soc_sensor(add_battery_assets, db):
    """Regression: unresolved/resolved reporting works without a state_of_charge sensor.

    A battery has ``soc-minima`` constraints but no ``state-of-charge`` sensor
    configured in the flex model.  The production code must still produce
    unresolved/resolved entries keyed by the asset ID (not the SoC sensor ID).
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

    # No "state-of-charge" key in flex_model — intentionally omitted.
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
                    "value": "0.9 MWh",  # unreachable given the limited capacity
                }
            ],
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
    assert scheduling_result_entry is not None, "scheduling_result entry missing"

    scheduling_result = scheduling_result_entry["data"]
    assert isinstance(scheduling_result, SchedulingJobResult)

    # Result must be keyed by the asset ID, not by a SoC sensor ID.
    asset_id = battery.generic_asset.id

    unresolved = scheduling_result.unresolved
    entry = next((e for e in unresolved if e["asset"] == asset_id), None)
    assert entry is not None, (
        f"Expected an unresolved entry for asset ID {asset_id!r}; "
        f"got: {unresolved!r}"
    )
    assert "soc-minima" in entry
    # Only a single soc-minima datetime was defined in the flex model, so the
    # violation list holds exactly one entry.
    assert len(entry["soc-minima"]) == 1
    assert entry["soc-minima"][0]["violation"] == "260.0 kWh"
    assert entry["soc-minima"][0]["datetime"] == "2015-01-01T23:00:00+00:00"

    # No soc-maxima constraint was set.
    assert "soc-maxima" not in entry

    # No soc-maxima constraint defined, so resolved should be empty.
    assert scheduling_result.resolved == []


def test_unresolved_targets_most_relevant_only_flag_soc_minima_violations(
    add_battery_assets, db
):
    """Test the ``most_relevant_only`` flag of ``_compute_unresolved_targets`` for unresolved soc-minima.

    A battery starts at 0.4 MWh with a very limited charging capacity (0.01 MW),
    so it can gain at most 0.01 * 24 = 0.24 MWh over the 24-hour schedule,
    reaching a max SoC of ~0.64 MWh. Three soc-minima checkpoints of 0.9 MWh
    are set at different times, all of which are unreachable given this
    physical limit, regardless of how the scheduler distributes charging.

    With the default ``most_relevant_only=False``, ``_compute_unresolved_targets``
    reports every violated slot (all three checkpoints, chronologically ordered).
    With ``most_relevant_only=True``, it reports only the first (earliest) violation.
    """
    _, battery = get_sensors_from_db(
        db, add_battery_assets, battery_name="Test battery"
    )
    soc_sensor = Sensor(
        name="state-of-charge-all-flag-minima-test",
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

    # All three checkpoints require 0.9 MWh, which is unreachable at any point
    # in the schedule given the 0.01 MW charging limit (max reachable ~0.64 MWh).
    violation_datetimes = [
        "2015-01-01T06:00:00+01:00",
        "2015-01-01T12:00:00+01:00",
        "2015-01-02T00:00:00+01:00",
    ]

    scheduler: Scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={
            "soc-at-start": f"{soc_at_start} MWh",
            "soc-min": "0 MWh",
            "soc-max": "1 MWh",
            "power-capacity": "0.01 MVA",
            "soc-minima": [
                {"datetime": dt, "value": "0.9 MWh"} for dt in violation_datetimes
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

    # Intercept the private helper to also capture what it would return with
    # most_relevant_only=True, without affecting the (default
    # most_relevant_only=False) result used by compute().
    captured: dict = {}
    original = StorageScheduler._compute_unresolved_targets

    def spy(
        self,
        flex_model,
        soc_schedule_mwh,
        start,
        end,
        resolution,
        most_relevant_only=False,
    ):
        captured["most_relevant_only"] = original(
            self,
            flex_model,
            soc_schedule_mwh,
            start,
            end,
            resolution,
            most_relevant_only=True,
        )
        return original(
            self,
            flex_model,
            soc_schedule_mwh,
            start,
            end,
            resolution,
            most_relevant_only=most_relevant_only,
        )

    with mock.patch.object(StorageScheduler, "_compute_unresolved_targets", spy):
        results = scheduler.compute()

    scheduling_result_entry = next(
        (r for r in results if r.get("name") == "scheduling_result"), None
    )
    assert scheduling_result_entry is not None
    scheduling_result = scheduling_result_entry["data"]
    asset_id = battery.generic_asset.id

    # --- most_relevant_only=False (the default used by compute()) ---
    entry = next(
        (e for e in scheduling_result.unresolved if e["asset"] == asset_id), None
    )
    assert entry is not None
    assert "soc-minima" in entry
    violations = entry["soc-minima"]
    assert len(violations) == len(violation_datetimes), (
        f"Expected all {len(violation_datetimes)} violated slots to be reported, "
        f"got: {violations!r}"
    )
    expected_utc_datetimes = [
        pd.Timestamp(dt).tz_convert("UTC").isoformat() for dt in violation_datetimes
    ]
    # Entries must be chronologically ordered and match the checkpoint datetimes.
    assert [v["datetime"] for v in violations] == expected_utc_datetimes
    for v in violations:
        assert v["violation"].endswith(" kWh")
        assert float(v["violation"].replace(" kWh", "")) > 0

    # --- most_relevant_only=True ---
    unresolved_most_relevant_only, _resolved_most_relevant_only = captured[
        "most_relevant_only"
    ]
    entry_most_relevant_only = next(
        (e for e in unresolved_most_relevant_only if e["asset"] == asset_id), None
    )
    assert entry_most_relevant_only is not None
    # Only the first (earliest) violation should be reported.
    assert len(entry_most_relevant_only["soc-minima"]) == 1
    assert entry_most_relevant_only["soc-minima"][0] == violations[0]


def test_unresolved_targets_most_relevant_only_flag_soc_minima_resolved_margins(
    add_battery_assets, db
):
    """Test the ``most_relevant_only`` flag of ``_compute_unresolved_targets`` for resolved (met) soc-minima.

    A battery starts at 0.4 MWh with plenty of charging capacity, a positive
    consumption price, and a negative production price (so that neither charging
    nor discharging is ever done without reason). Two soc-minima checkpoints are
    set: an earlier, tighter one (0.5 MWh) and a later, much slacker one (0.1 MWh).
    Both are met, but with different margins: the battery charges up to 0.5 MWh as
    soon as possible (``prefer-charging-sooner`` defaults to True) to satisfy the
    tighter, earlier checkpoint, and then has no incentive to move further, so it
    stays there — leaving zero margin at the tighter checkpoint and a much larger
    margin at the slacker, later checkpoint.

    With the default ``most_relevant_only=False``, both met slots are reported
    (chronologically ordered). With ``most_relevant_only=True``, only the slot
    with the tightest (smallest) margin is reported.
    """
    _, battery = get_sensors_from_db(
        db, add_battery_assets, battery_name="Test battery"
    )
    soc_sensor = Sensor(
        name="state-of-charge-all-flag-margins-test",
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
    # A (small) negative production price means discharging (selling energy)
    # incurs a cost rather than earning revenue, so the battery has no incentive
    # to move away from a checkpoint once it has been satisfied.
    production_prices = pd.Series(-1, index=index)

    tight_datetime = "2015-01-01T06:00:00+01:00"
    slack_datetime = "2015-01-02T00:00:00+01:00"

    scheduler: Scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={
            "soc-at-start": f"{soc_at_start} MWh",
            "soc-min": "0 MWh",
            "soc-max": "1 MWh",
            "power-capacity": "2 MVA",
            "soc-minima": [
                {"datetime": tight_datetime, "value": "0.5 MWh"},
                {"datetime": slack_datetime, "value": "0.1 MWh"},
            ],
            "state-of-charge": {"sensor": soc_sensor.id},
        },
        flex_context={
            "consumption-price": series_to_ts_specs(consumption_prices, unit="EUR/MWh"),
            "production-price": series_to_ts_specs(production_prices, unit="EUR/MWh"),
            "site-power-capacity": "2 MW",
            "soc-minima-breach-price": "1 EUR/kWh",  # soft constraint
        },
        return_multiple=True,
    )

    # Intercept the private helper to also capture what it would return with
    # most_relevant_only=True, without affecting the (default
    # most_relevant_only=False) result used by compute().
    captured: dict = {}
    original = StorageScheduler._compute_unresolved_targets

    def spy(
        self,
        flex_model,
        soc_schedule_mwh,
        start,
        end,
        resolution,
        most_relevant_only=False,
    ):
        captured["most_relevant_only"] = original(
            self,
            flex_model,
            soc_schedule_mwh,
            start,
            end,
            resolution,
            most_relevant_only=True,
        )
        return original(
            self,
            flex_model,
            soc_schedule_mwh,
            start,
            end,
            resolution,
            most_relevant_only=most_relevant_only,
        )

    with mock.patch.object(StorageScheduler, "_compute_unresolved_targets", spy):
        results = scheduler.compute()

    scheduling_result_entry = next(
        (r for r in results if r.get("name") == "scheduling_result"), None
    )
    assert scheduling_result_entry is not None
    scheduling_result = scheduling_result_entry["data"]
    asset_id = battery.generic_asset.id

    # No violations expected: both checkpoints are met.
    assert scheduling_result.unresolved == []

    # --- most_relevant_only=False (the default used by compute()) ---
    entry = next(
        (e for e in scheduling_result.resolved if e["asset"] == asset_id), None
    )
    assert entry is not None
    assert "soc-minima" in entry
    margins = entry["soc-minima"]
    assert (
        len(margins) == 2
    ), f"Expected both met slots to be reported, got: {margins!r}"
    expected_utc_datetimes = [
        pd.Timestamp(dt).tz_convert("UTC").isoformat()
        for dt in (tight_datetime, slack_datetime)
    ]
    assert [m["datetime"] for m in margins] == expected_utc_datetimes
    margin_values = [float(m["margin"].replace(" kWh", "")) for m in margins]
    assert all(v >= 0 for v in margin_values)
    # The tighter (earlier, higher-value) checkpoint should have the smaller margin.
    tight_margin, slack_margin = margin_values
    assert tight_margin < slack_margin

    # --- most_relevant_only=True ---
    _unresolved_most_relevant_only, resolved_most_relevant_only = captured[
        "most_relevant_only"
    ]
    entry_most_relevant_only = next(
        (e for e in resolved_most_relevant_only if e["asset"] == asset_id), None
    )
    assert entry_most_relevant_only is not None
    # Only the tightest (smallest) margin slot should be reported.
    assert len(entry_most_relevant_only["soc-minima"]) == 1
    expected_tightest = min(
        margins, key=lambda m: float(m["margin"].replace(" kWh", ""))
    )
    assert entry_most_relevant_only["soc-minima"][0] == expected_tightest


def test_deserialize_storage_soc_at_start_from_state_of_charge_sensor(
    add_charging_station_assets, setup_markets, setup_sources, db
):
    start = pd.Timestamp("2015-01-01T00:00:00+01:00")
    end = start + timedelta(hours=12)
    charging_station = add_charging_station_assets["Test charging station"]
    power_sensor = next(s for s in charging_station.sensors if s.name == "power")
    soc_sensor = add_charging_station_assets["uni-soc"]

    db.session.add(
        TimedBelief(
            sensor=soc_sensor,
            source=setup_sources["Seita"],
            event_start=start - timedelta(minutes=45),
            belief_horizon=timedelta(0),
            event_value=2.75,
        )
    )
    db.session.flush()

    scheduler = StorageScheduler(
        power_sensor,
        start,
        end,
        power_sensor.event_resolution,
        flex_model={
            "state-of-charge": {"sensor": soc_sensor.id},
            "soc-min": "0 MWh",
            "soc-max": "5 MWh",
            "power-capacity": "2 MW",
        },
        flex_context={"consumption-price": {"sensor": setup_markets["epex_da"].id}},
    )

    scheduler.deserialize_config()

    assert scheduler.flex_model["soc_at_start"] == 2.75
    assert scheduler.flex_model["soc_unit"] == "MWh"


def test_deserialize_storage_soc_at_start_from_filtered_state_of_charge_sensor(
    add_charging_station_assets, setup_markets, setup_sources, db
):
    start = pd.Timestamp("2015-01-01T00:00:00+01:00")
    end = start + timedelta(hours=12)
    charging_station = add_charging_station_assets["Test charging station"]
    power_sensor = next(s for s in charging_station.sensors if s.name == "power")
    soc_sensor = add_charging_station_assets["uni-soc"]

    db.session.add(
        TimedBelief(
            sensor=soc_sensor,
            source=setup_sources["Seita"],
            event_start=start - timedelta(minutes=30),
            belief_horizon=timedelta(0),
            event_value=2.75,
        )
    )
    db.session.add(
        TimedBelief(
            sensor=soc_sensor,
            source=setup_sources["ENTSO-E"],
            event_start=start - timedelta(minutes=30),
            belief_horizon=timedelta(minutes=-15),
            event_value=9.75,
        )
    )
    db.session.flush()

    scheduler = StorageScheduler(
        power_sensor,
        start,
        end,
        power_sensor.event_resolution,
        flex_model={
            "state-of-charge": {
                "sensor": soc_sensor.id,
                "sources": [setup_sources["Seita"].id],
            },
            "soc-min": "0 MWh",
            "soc-max": "5 MWh",
            "power-capacity": "2 MW",
        },
        flex_context={"consumption-price": {"sensor": setup_markets["epex_da"].id}},
    )

    scheduler.deserialize_config()

    assert scheduler.flex_model["soc_at_start"] == 2.75


def test_deserialize_storage_efficiency_from_filtered_sensor(
    add_battery_assets, setup_sources, db
):
    battery = add_battery_assets["Test battery"]
    power_sensor = next(s for s in battery.sensors if s.name == "power")
    efficiency_sensor = Sensor(
        name="storage-efficiency",
        generic_asset=battery,
        event_resolution=timedelta(hours=1),
        unit="%",
    )
    db.session.add(efficiency_sensor)
    db.session.add(
        TimedBelief(
            sensor=efficiency_sensor,
            source=setup_sources["Seita"],
            event_start="2015-01-01T00:00:00+01:00",
            belief_horizon=timedelta(0),
            event_value=90,
        )
    )
    db.session.add(
        TimedBelief(
            sensor=efficiency_sensor,
            source=setup_sources["ENTSO-E"],
            event_start="2015-01-01T00:00:00+01:00",
            belief_horizon=timedelta(minutes=-15),
            event_value=80,
        )
    )
    db.session.flush()

    scheduler = StorageScheduler(
        power_sensor,
        pd.Timestamp("2015-01-01T00:00:00+01:00"),
        pd.Timestamp("2015-01-01T02:00:00+01:00"),
        power_sensor.event_resolution,
        flex_model={
            "soc-at-start": "2.5 MWh",
            "soc-min": "0 MWh",
            "soc-max": "5 MWh",
            "power-capacity": "2 MW",
            "storage-efficiency": {
                "sensor": efficiency_sensor.id,
                "sources": [setup_sources["Seita"].id],
            },
        },
        flex_context={"consumption-price": "1 EUR/MWh"},
    )

    _, _, _, _, _, device_constraints, _, _ = scheduler._prepare(skip_validation=True)

    assert device_constraints[0]["efficiency"].iloc[0] == pytest.approx(0.9**0.25)


def test_deserialize_storage_soc_at_start_from_state_of_charge_time_series(
    add_charging_station_assets, setup_markets
):
    start = pd.Timestamp("2015-01-01T00:00:00+01:00")
    end = start + timedelta(hours=12)
    charging_station = add_charging_station_assets["Test charging station"]
    power_sensor = next(s for s in charging_station.sensors if s.name == "power")

    scheduler = StorageScheduler(
        power_sensor,
        start,
        end,
        power_sensor.event_resolution,
        flex_model={
            "state-of-charge": [
                {
                    "start": "2014-12-31T23:30:00+01:00",
                    "end": "2015-01-01T00:30:00+01:00",
                    "value": "3.1 MWh",
                }
            ],
            "soc-min": "0 MWh",
            "soc-max": "5 MWh",
            "power-capacity": "2 MW",
        },
        flex_context={"consumption-price": {"sensor": setup_markets["epex_da"].id}},
    )

    scheduler.deserialize_config()

    assert scheduler.flex_model["soc_at_start"] == 3.1


def test_deserialize_storage_soc_at_start_rejects_stale_state_of_charge_sensor(
    add_charging_station_assets, setup_markets, setup_sources, db
):
    start = pd.Timestamp("2015-01-01T06:00:00+01:00")
    end = start + timedelta(hours=12)
    charging_station = add_charging_station_assets["Test charging station"]
    power_sensor = next(s for s in charging_station.sensors if s.name == "power")
    soc_sensor = add_charging_station_assets["uni-soc"]

    db.session.add(
        TimedBelief(
            sensor=soc_sensor,
            source=setup_sources["Seita"],
            event_start=start - timedelta(hours=2),
            belief_horizon=timedelta(0),
            event_value=2.75,
        )
    )
    db.session.flush()

    scheduler = StorageScheduler(
        power_sensor,
        start,
        end,
        power_sensor.event_resolution,
        flex_model={
            "state-of-charge": {"sensor": soc_sensor.id},
            "soc-min": "0 MWh",
            "soc-max": "5 MWh",
            "power-capacity": "2 MW",
        },
        flex_context={"consumption-price": {"sensor": setup_markets["epex_da"].id}},
    )

    with pytest.raises(ValueError, match="No recent state-of-charge value found"):
        scheduler.deserialize_config()


def test_deserialize_storage_soc_at_start_rejects_missing_state_of_charge_sensor(
    add_charging_station_assets, setup_markets
):
    start = pd.Timestamp("2015-01-01T00:00:00+01:00")
    end = start + timedelta(hours=12)
    charging_station = add_charging_station_assets["Test charging station"]
    power_sensor = next(s for s in charging_station.sensors if s.name == "power")

    scheduler = StorageScheduler(
        power_sensor,
        start,
        end,
        power_sensor.event_resolution,
        flex_model={
            "state-of-charge": {"sensor": 999999},
            "soc-min": "0 MWh",
            "soc-max": "5 MWh",
            "power-capacity": "2 MW",
        },
        flex_context={"consumption-price": {"sensor": setup_markets["epex_da"].id}},
    )

    with pytest.raises(
        ValueError,
        match="State-of-charge sensor with id 999999 was not found.",
    ):
        scheduler._resolve_soc_at_start_from_state_of_charge(  # noqa: SLF001
            scheduler.flex_model, power_sensor
        )


def test_resolve_soc_at_start_from_percent_sensor_uses_device_sensor_fallback(
    add_charging_station_assets, db, setup_sources
):
    start = pd.Timestamp("2015-01-01T00:00:00+01:00")
    end = start + timedelta(hours=12)
    charging_station = add_charging_station_assets["Test charging station"]
    power_sensor = next(s for s in charging_station.sensors if s.name == "power")
    soc_sensor = Sensor(
        name="soc-percent",
        generic_asset=charging_station,
        event_resolution=timedelta(0),
        unit="%",
    )
    db.session.add(soc_sensor)
    db.session.flush()
    db.session.add(
        TimedBelief(
            sensor=soc_sensor,
            source=setup_sources["Seita"],
            event_start=start - timedelta(minutes=15),
            belief_horizon=timedelta(0),
            event_value=50,
        )
    )
    db.session.flush()

    scheduler = StorageScheduler(
        asset_or_sensor=power_sensor.generic_asset.parent_asset,
        start=start,
        end=end,
        resolution=power_sensor.event_resolution,
        flex_model={},
    )

    assert scheduler.sensor is None
    assert (
        scheduler._resolve_soc_at_start_from_sensor(  # noqa: SLF001
            soc_sensor, {}, power_sensor
        )
        == 2.5
    )
