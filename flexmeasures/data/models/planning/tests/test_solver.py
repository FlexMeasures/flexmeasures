from datetime import datetime, timedelta
import pytest

import numpy as np
import pandas as pd

from flexmeasures.data.models.assets import Asset
from flexmeasures.data.models.markets import Market
from flexmeasures.data.models.planning.battery import schedule_battery
from flexmeasures.data.models.planning.charging_station import schedule_charging_station
from flexmeasures.utils.calculations import integrate_time_series
from flexmeasures.utils.time_utils import as_server_time


def test_battery_solver_day_1():
    epex_da = Market.query.filter(Market.name == "epex_da").one_or_none()
    battery = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    start = as_server_time(datetime(2015, 1, 1))
    end = as_server_time(datetime(2015, 1, 2))
    resolution = timedelta(minutes=15)
    soc_at_start = battery.soc_in_mwh
    schedule = schedule_battery(battery, epex_da, start, end, resolution, soc_at_start)
    soc_schedule = integrate_time_series(schedule, soc_at_start, decimal_precision=6)

    with pd.option_context("display.max_rows", None, "display.max_columns", 3):
        print(soc_schedule)

    # Check if constraints were met
    assert min(schedule.values) >= battery.capacity_in_mw * -1
    assert max(schedule.values) <= battery.capacity_in_mw
    for soc in soc_schedule.values:
        assert soc >= battery.min_soc_in_mwh
        assert soc <= battery.max_soc_in_mwh


def test_battery_solver_day_2():
    epex_da = Market.query.filter(Market.name == "epex_da").one_or_none()
    battery = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    start = as_server_time(datetime(2015, 1, 2))
    end = as_server_time(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    soc_at_start = battery.soc_in_mwh
    schedule = schedule_battery(battery, epex_da, start, end, resolution, soc_at_start)
    soc_schedule = integrate_time_series(schedule, soc_at_start, decimal_precision=6)

    with pd.option_context("display.max_rows", None, "display.max_columns", 3):
        print(soc_schedule)

    # Check if constraints were met
    assert min(schedule.values) >= battery.capacity_in_mw * -1
    assert max(schedule.values) <= battery.capacity_in_mw
    for soc in soc_schedule.values:
        assert soc >= battery.min_soc_in_mwh
        assert soc <= battery.max_soc_in_mwh

    # Check whether the resulting soc schedule follows our expectations for 8 expensive, 8 cheap and 8 expensive hours
    assert (
        soc_schedule.iloc[-1] == battery.min_soc_in_mwh
    )  # Battery sold out at the end of its planning horizon
    assert (
        soc_schedule.loc[start + timedelta(hours=8)] == battery.min_soc_in_mwh
    )  # Sell what you begin with
    assert (
        soc_schedule.loc[start + timedelta(hours=16)] == battery.max_soc_in_mwh
    )  # Buy what you can to sell later


@pytest.mark.parametrize(
    "target_soc, charging_station_name",
    [
        (1, "Test charging station"),
        (5, "Test charging station"),
        (0, "Test charging station (bidirectional)"),
        (5, "Test charging station (bidirectional)"),
    ],
)
def test_charging_station_solver_day_2(target_soc, charging_station_name):
    """Starting with a state of charge 1 kWh, within 2 hours we should be able to reach
    any state of charge in the range [1, 5] kWh for a unidirectional station,
    or [0, 5] for a bidirectional station."""
    soc_at_start = 1
    duration_until_target = timedelta(hours=2)

    epex_da = Market.query.filter(Market.name == "epex_da").one_or_none()
    charging_station = Asset.query.filter(
        Asset.name == charging_station_name
    ).one_or_none()
    start = as_server_time(datetime(2015, 1, 2))
    end = as_server_time(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    target_soc_datetime = start + duration_until_target
    soc_targets = pd.Series(
        np.nan, index=pd.date_range(start, end, freq=resolution, closed="right")
    )
    soc_targets.loc[target_soc_datetime] = target_soc
    consumption_schedule = schedule_charging_station(
        charging_station, epex_da, start, end, resolution, soc_at_start, soc_targets
    )
    soc_schedule = integrate_time_series(
        consumption_schedule, soc_at_start, decimal_precision=6
    )

    # Check if constraints were met
    assert min(consumption_schedule.values) >= charging_station.capacity_in_mw * -1
    assert max(consumption_schedule.values) <= charging_station.capacity_in_mw
    print(consumption_schedule.head(12))
    print(soc_schedule.head(12))
    assert abs(soc_schedule.loc[target_soc_datetime] - target_soc) < 0.00001
