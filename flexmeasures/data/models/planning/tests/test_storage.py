from datetime import datetime, timedelta

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
    np.testing.assert_almost_equal(costs["electricity energy 0"], 100 * (1 - 0.4))
    # 24000 EUR for any 24 kW consumption breach priced at 1000 EUR/kW
    np.testing.assert_almost_equal(costs["any consumption breach 0"], 1000 * (25 - 1))
    # 24000 EUR for each 24 kW consumption breach per hour priced at 1000 EUR/kWh
    np.testing.assert_almost_equal(
        costs["all consumption breaches 0"], 1000 * (25 - 1) * 96 / 4
    )
    # No production breaches
    np.testing.assert_almost_equal(costs["any production breach 0"], 0)
    np.testing.assert_almost_equal(costs["all production breaches 0"], 0 * 96)
    # 1.3 EUR for the 5 kW extra consumption peak priced at 260 EUR/MW
    np.testing.assert_almost_equal(costs["consumption peak 0"], 260 / 1000 * (25 - 20))
    # No production peak
    np.testing.assert_almost_equal(costs["production peak 0"], 0)

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
