from __future__ import annotations

from datetime import datetime, timedelta
import pytest

import pandas as pd

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.utils.time_utils import as_server_time


@pytest.fixture(scope="module", autouse=True)
def setup_planning_test_data(db, add_market_prices, add_charging_station_assets):
    """
    Set up data for all planning tests.
    """
    print("Setting up data for planning tests on %s" % db.engine)


@pytest.fixture(scope="module")
def add_inflexible_devices(db, setup_accounts) -> dict[str, Sensor]:
    """
    Set up inflexible devices.
    """
    building_type = GenericAssetType(name="building")
    db.session.add(building_type)
    test_building = GenericAsset(
        name="Test building",
        generic_asset_type=building_type,
        owner=setup_accounts["Prosumer"],
    )
    db.session.add(test_building)
    pv_sensor = Sensor(
        name="PV power sensor",
        generic_asset=test_building,
        event_resolution=timedelta(hours=1),
        unit="kW",
        attributes={"capacity_in_mw": 2},
    )
    db.session.add(pv_sensor)
    return {pv_sensor.name: pv_sensor}


@pytest.fixture(scope="module")
def add_inflexible_device_forecasts(
    db, add_inflexible_devices, setup_sources
) -> dict[Sensor, list[int | float]]:
    """
    Set up inflexible devices and forecasts.
    """
    # 2 days of test data (each 8 hours at zero capacity, 8 hours at 90% capacity, and again 8 hours at zero capacity)
    time_slots = pd.date_range(
        datetime(2015, 1, 1), datetime(2015, 1, 3), freq="1H", closed="left"
    )
    headroom = 0.1  # 90% of nominal capacity
    sensor = add_inflexible_devices["PV power sensor"]
    capacity = sensor.get_attribute("capacity_in_mw")
    values = ([0] * 8 + [(1 - headroom) * capacity] * 8 + [0] * 8) * (
        len(time_slots) // 24
    )
    day1_beliefs = [
        TimedBelief(
            event_start=as_server_time(dt),
            belief_horizon=timedelta(hours=0),
            event_value=val,
            source=setup_sources["Seita"],
            sensor=sensor,
        )
        for dt, val in zip(time_slots, values)
    ]
    db.session.add_all(day1_beliefs)
    return {sensor: values}
