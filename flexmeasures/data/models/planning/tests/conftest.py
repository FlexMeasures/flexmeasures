from __future__ import annotations

from datetime import datetime, timedelta
from random import random
import pytest

import numpy as np
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
    )
    db.session.add(pv_sensor)
    return {pv_sensor.name: pv_sensor}


@pytest.fixture(scope="module")
def add_inflexible_device_forecasts(
    db, add_inflexible_devices, setup_sources
) -> dict[str, Sensor]:
    """
    Set up inflexible devices and forecasts.
    """
    # one day of test data (one complete sine curve)
    time_slots = pd.date_range(
        datetime(2015, 1, 1), datetime(2015, 1, 2), freq="1H", closed="left"
    )
    values = [
        random() * (1 + np.sin(x * 2 * np.pi / 24)) for x in range(len(time_slots))
    ]
    day1_beliefs = [
        TimedBelief(
            event_start=as_server_time(dt),
            belief_horizon=timedelta(hours=0),
            event_value=val,
            source=setup_sources["Seita"],
            sensor=add_inflexible_devices["PV power sensor"],
        )
        for dt, val in zip(time_slots, values)
    ]
    db.session.add_all(day1_beliefs)
    return add_inflexible_devices
