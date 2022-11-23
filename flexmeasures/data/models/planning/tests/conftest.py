from __future__ import annotations

from datetime import timedelta
import pytest

from timely_beliefs.sensors.func_store.knowledge_horizons import at_date
import pandas as pd

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.planning.utils import initialize_index
from flexmeasures.data.models.time_series import Sensor, TimedBelief


@pytest.fixture(scope="module", autouse=True)
def setup_planning_test_data(db, add_market_prices, add_charging_station_assets):
    """
    Set up data for all planning tests.
    """
    print("Setting up data for planning tests on %s" % db.engine)


@pytest.fixture(scope="module")
def create_test_tariffs(db, setup_accounts, setup_sources) -> dict[str, Sensor]:
    """Create a fixed consumption tariff and a fixed feed-in tariff that is lower."""

    market_type = GenericAssetType(
        name="tariff market",
    )
    db.session.add(market_type)
    contract = GenericAsset(
        name="supply contract",
        generic_asset_type=market_type,
        owner=setup_accounts["Supplier"],
    )
    db.session.add(contract)
    consumption_price_sensor = Sensor(
        name="fixed consumption tariff",
        generic_asset=contract,
        event_resolution=timedelta(hours=24 * 365),
        unit="EUR/MWh",
        knowledge_horizon=(at_date, {"knowledge_time": "2014-11-01T00:00+01:00"}),
    )
    db.session.add(consumption_price_sensor)
    production_price_sensor = Sensor(
        name="fixed feed-in tariff",
        generic_asset=contract,
        event_resolution=timedelta(hours=24 * 365),
        unit="EUR/MWh",
        knowledge_horizon=(at_date, {"knowledge_time": "2014-11-01T00:00+01:00"}),
    )
    db.session.add(production_price_sensor)

    # Add prices
    consumption_price = TimedBelief(
        event_start="2015-01-01T00:00+01:00",
        belief_time="2014-11-01T00:00+01:00",  # publication date
        event_value=300 * 1.21,
        source=setup_sources["Seita"],
        sensor=consumption_price_sensor,
    )
    db.session.add(consumption_price)
    production_price = TimedBelief(
        event_start="2015-01-01T00:00+01:00",
        belief_time="2014-11-01T00:00+01:00",  # publication date
        event_value=300,
        source=setup_sources["Seita"],
        sensor=production_price_sensor,
    )
    db.session.add(production_price)
    db.session.flush()  # make sure that prices are assigned to price sensors
    return {
        "consumption_price_sensor": consumption_price_sensor,
        "production_price_sensor": production_price_sensor,
    }


@pytest.fixture(scope="module")
def building(db, setup_accounts, setup_markets) -> GenericAsset:
    """
    Set up a building.
    """
    building_type = GenericAssetType(name="building")
    db.session.add(building_type)
    building = GenericAsset(
        name="building",
        generic_asset_type=building_type,
        owner=setup_accounts["Prosumer"],
        attributes=dict(
            market_id=setup_markets["epex_da"].id,
            capacity_in_mw=2,
        ),
    )
    db.session.add(building)
    return building


@pytest.fixture(scope="module")
def flexible_devices(db, building) -> dict[str, Sensor]:
    """
    Set up power sensors for flexible devices:
    - A battery
    - A Charge Point (todo)
    """
    battery_sensor = Sensor(
        name="battery power sensor",
        generic_asset=building,
        event_resolution=timedelta(minutes=15),
        attributes=dict(
            capacity_in_mw=2,
            max_soc_in_mwh=5,
            min_soc_in_mwh=0,
        ),
        unit="MW",
    )
    db.session.add(battery_sensor)
    return {
        battery_sensor.name: battery_sensor,
    }


@pytest.fixture(scope="module")
def inflexible_devices(db, building) -> dict[str, Sensor]:
    """
    Set up power sensors for inflexible devices:
    - A PV panel
    - Residual building demand
    """
    pv_sensor = Sensor(
        name="PV power sensor",
        generic_asset=building,
        event_resolution=timedelta(hours=1),
        unit="kW",
        attributes={"capacity_in_mw": 2},
    )
    db.session.add(pv_sensor)
    residual_demand_sensor = Sensor(
        name="residual demand power sensor",
        generic_asset=building,
        event_resolution=timedelta(hours=1),
        unit="kW",
        attributes={"capacity_in_mw": 2},
    )
    db.session.add(residual_demand_sensor)
    return {
        pv_sensor.name: pv_sensor,
        residual_demand_sensor.name: residual_demand_sensor,
    }


@pytest.fixture(scope="module")
def add_inflexible_device_forecasts(
    db, inflexible_devices, setup_sources
) -> dict[Sensor, list[int | float]]:
    """
    Set up inflexible devices and forecasts.
    """
    # 2 days of test data
    time_slots = initialize_index(
        start=pd.Timestamp("2015-01-01").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2015-01-03").tz_localize("Europe/Amsterdam"),
        resolution="15T",
    )

    # PV (8 hours at zero capacity, 8 hours at 90% capacity, and again 8 hours at zero capacity)
    headroom = 0.1  # 90% of nominal capacity
    pv_sensor = inflexible_devices["PV power sensor"]
    capacity = pv_sensor.get_attribute("capacity_in_mw")
    pv_values = (
        [0] * (8 * 4) + [(1 - headroom) * capacity] * (8 * 4) + [0] * (8 * 4)
    ) * (len(time_slots) // (24 * 4))
    add_as_beliefs(db, pv_sensor, pv_values, time_slots, setup_sources["Seita"])

    # Residual demand (1 MW continuously)
    residual_demand_sensor = inflexible_devices["residual demand power sensor"]
    residual_demand_values = [-1] * len(time_slots)
    add_as_beliefs(
        db,
        residual_demand_sensor,
        residual_demand_values,
        time_slots,
        setup_sources["Seita"],
    )

    return {
        pv_sensor: pv_values,
        residual_demand_sensor: residual_demand_values,
    }


def add_as_beliefs(db, sensor, values, time_slots, source):
    beliefs = [
        TimedBelief(
            event_start=dt,
            belief_time=time_slots[0],
            event_value=val,
            source=source,
            sensor=sensor,
        )
        for dt, val in zip(time_slots, values)
    ]
    db.session.add_all(beliefs)
