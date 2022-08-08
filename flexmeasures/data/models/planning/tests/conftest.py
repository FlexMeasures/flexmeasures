from __future__ import annotations

from datetime import datetime, timedelta
import pytest

import pandas as pd

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief


@pytest.fixture(scope="module", autouse=True)
def setup_planning_test_data(db, add_market_prices, add_charging_station_assets):
    """
    Set up data for all planning tests.
    """
    print("Setting up data for planning tests on %s" % db.engine)


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
    time_slots = pd.date_range(
        datetime(2015, 1, 1),
        datetime(2015, 1, 3),
        freq="15T",
        closed="left",
        tz="Europe/Amsterdam",
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
