from datetime import datetime, timedelta

import pytz
import pytest

import numpy as np
import pandas as pd

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.planning import Scheduler
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.data.models.planning.utils import initialize_index
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.planning.tests.utils import (
    check_constraints,
    get_sensors_from_db,
    series_to_ts_specs,
)
from flexmeasures.data.services.utils import get_or_create_model


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
    np.testing.assert_almost_equal(costs["electricity net energy"], 100 * (1 - 0.4))
    # 24000 EUR for any 24 kW consumption breach priced at 1000 EUR/kW
    np.testing.assert_almost_equal(
        costs["electricity any consumption breach"], 1000 * (25 - 1)
    )
    # 24000 EUR for each 24 kW consumption breach per hour priced at 1000 EUR/kWh
    np.testing.assert_almost_equal(
        costs["electricity all consumption breaches"], 1000 * (25 - 1) * 96 / 4
    )
    # No production breaches
    np.testing.assert_almost_equal(costs["electricity any production breach"], 0)
    np.testing.assert_almost_equal(costs["electricity all production breaches"], 0 * 96)
    # 1.3 EUR for the 5 kW extra consumption peak priced at 260 EUR/MW
    np.testing.assert_almost_equal(
        costs["electricity consumption peak"], 260 / 1000 * (25 - 20)
    )
    # No production peak
    np.testing.assert_almost_equal(costs["electricity production peak"], 0)

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


def test_storage_scheduler_chp_coupling(app, db):
    """Test that the StorageScheduler enforces CHP coupling constraints between devices.

    Models a Combined Heat and Power unit with three sensors.

    In the flex-model, the coupling coefficients are entered as positive magnitudes::

        gas input   -> 1.0
        heat output -> 0.5
        power output -> 0.3

    Internally, the CHP is interpreted with the signed commodity-flow coefficients::

        P_gas   ->  1.0
        P_heat  -> -0.5
        P_power -> -0.3

    The returned storage schedule for the heat buffer is still positive, because this
    test uses the storage sign convention for buffer charging.

    - d=0  gas input:    CHP gas consumption
    - d=1  heat output:  CHP heat -> heat buffer
    - d=2  power output: CHP electricity production

    The heat output is forced to exactly 5 kW per step by combining:
    - ``production-capacity: "0 kW"``  (hard lower bound: derivative_min = 0)
    - ``consumption-capacity: "5 kW"`` (hard upper bound: derivative_max = 0.005 MW)
    - ``soc-targets`` requiring 20 kWh at the end of the 4-hour window

    With soc_at_start = 0 and max 5 kW over 4 × 1-hour steps the only feasible
    solution is P_heat = 5 kW every step. Substituting P_heat = 5 kW gives
    alpha = 5 / 0.5 = 10 kW, so:

        P_gas   =  1.0 × 10 kW = 10 kW
        P_power = −0.3 × 10 kW = −3 kW
    """
    # ---- asset type + asset
    chp_type = get_or_create_model(GenericAssetType, name="chp-plant")
    chp = GenericAsset(name="CHP plant (coupling test)", generic_asset_type=chp_type)
    db.session.add(chp)
    db.session.flush()

    # ---- schedule window
    start = pd.Timestamp("2026-01-01T00:00:00+01:00")
    end = pd.Timestamp("2026-01-01T04:00:00+01:00")
    resolution = timedelta(hours=1)

    # CHP efficiencies (same values as the factory scenario in test_commitments.py)
    ETA_HEAT = 0.5  # fraction of gas input that becomes heat
    ETA_POWER = 0.3  # fraction of gas input that becomes electricity

    # ---- sensors
    gas_input_sensor = Sensor(
        name="CHP gas input (coupling test)",
        generic_asset=chp,
        unit="MW",
        event_resolution=resolution,
    )
    heat_output_sensor = Sensor(
        name="CHP heat output (coupling test)",
        generic_asset=chp,
        unit="MW",
        event_resolution=resolution,
    )
    power_output_sensor = Sensor(
        name="CHP power output (coupling test)",
        generic_asset=chp,
        unit="MW",
        event_resolution=resolution,
    )
    db.session.add_all([gas_input_sensor, heat_output_sensor, power_output_sensor])
    db.session.flush()

    # ---- flex model
    # Flex-model coupling-coefficients are user-facing positive magnitudes.
    # The intended internal CHP coefficients are +1.0 for gas, -0.5 for heat,
    # and -0.3 for power.
    flex_model = [
        {
            # d=0: gas input — pure flow device (no SoC), can only consume gas.
            "sensor": gas_input_sensor.id,
            "power-capacity": "20 kW",
            "production-capacity": "0 kW",  # derivative_min = 0
            "coupling": "chp",
            "coupling-coefficient": 1.0,
        },
        {
            # d=1: heat output — tracks heat-buffer SoC, positive ems_power = heat
            # added to buffer. The SoC target forces P_heat = 5 kW per step.
            "sensor": heat_output_sensor.id,
            "soc-at-start": "0 MWh",
            "soc-min": "0 MWh",
            "soc-max": "0.02 MWh",  # 20 kWh — matches the SoC target
            "soc-targets": [
                {
                    # Single target at the schedule end: cumulative heat = 20 kWh.
                    # With max 5 kW and 4 × 1 h steps the only feasible solution
                    # is 5 kW every step.
                    "start": "2026-01-01T04:00:00+01:00",
                    "duration": "PT1H",
                    "value": "0.02 MWh",
                }
            ],
            "power-capacity": "5 kW",
            "consumption-capacity": "5 kW",
            "production-capacity": "0 kW",  # can only add heat, not extract
            "prefer-charging-sooner": True,
            "coupling": "chp",
            "coupling-coefficient": ETA_HEAT,  # = 0.5
        },
        {
            # d=2: power output — pure flow device (no SoC), can only produce
            # electricity (negative ems_power).
            "sensor": power_output_sensor.id,
            "power-capacity": "6 kW",
            "consumption-capacity": "0 kW",  # derivative_max = 0
            "coupling": "chp",
            "coupling-coefficient": ETA_POWER,  # = 0.3 (sign inferred from capacities)
        },
    ]

    flex_context = {
        "consumption-price": "50 EUR/MWh",
        "production-price": "50 EUR/MWh",
        "site-power-capacity": "1 MW",  # large enough to avoid EMS constraints
    }

    scheduler = StorageScheduler(
        asset_or_sensor=chp,
        start=start,
        end=end,
        resolution=resolution,
        flex_model=flex_model,
        flex_context=flex_context,
        return_multiple=True,
    )

    results = scheduler.compute(skip_validation=True)

    # ---- extract storage schedules per sensor
    storage_schedules = {
        r["sensor"]: r["data"] for r in results if r.get("name") == "storage_schedule"
    }

    assert gas_input_sensor in storage_schedules, "Gas input schedule missing"
    assert heat_output_sensor in storage_schedules, "Heat output schedule missing"
    assert power_output_sensor in storage_schedules, "Power output schedule missing"

    gas_schedule = storage_schedules[gas_input_sensor]
    heat_schedule = storage_schedules[heat_output_sensor]
    power_schedule = storage_schedules[power_output_sensor]

    # The SoC target of 20 kWh is met after 4 × 1-hour steps at 5 kW.
    # The schedule index runs from ``start`` to ``end`` inclusive (5 time slots),
    # so the last slot has no binding SoC constraint and the CHP is idle there.
    # All assertions therefore apply to the first four active slots only.
    active_steps = slice(None, -1)  # exclude the final trailing idle slot

    # Heat output is forced to exactly 5 kW per step by the SoC target.
    # alpha = P_heat / ETA_HEAT = 0.005 / 0.5 = 0.010 MW
    np.testing.assert_allclose(
        heat_schedule.iloc[active_steps],
        0.005,  # 5 kW expressed in MW
        rtol=1e-4,
        err_msg="Heat output should be exactly 5 kW per step (forced by SoC target)",
    )

    # Coupling: P_gas = 1.0 * alpha = 0.010 MW = 10 kW
    np.testing.assert_allclose(
        gas_schedule.iloc[active_steps],
        0.010,  # 10 kW expressed in MW
        rtol=1e-4,
        err_msg="Gas input must be 10 kW — determined by coupling (1.0 * alpha)",
    )

    # Coupling: P_power = -ETA_POWER * alpha = -0.3 * 0.010 MW = -0.003 MW = -3 kW
    np.testing.assert_allclose(
        power_schedule.iloc[active_steps],
        -0.003,  # -3 kW expressed in MW
        rtol=1e-4,
        err_msg="Power output must be -3 kW — determined by coupling (-0.3 * alpha)",
    )
