from datetime import datetime, timedelta
import pytest

import numpy as np
import pandas as pd

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.planning.battery import schedule_battery
from flexmeasures.data.models.planning.charging_station import schedule_charging_station
from flexmeasures.utils.calculations import integrate_time_series
from flexmeasures.utils.time_utils import as_server_time


TOLERANCE = 0.00001


def test_battery_solver_day_1(add_battery_assets):
    epex_da = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    battery = Sensor.query.filter(Sensor.name == "Test battery").one_or_none()
    assert Sensor.query.get(battery.get_attribute("market_id")) == epex_da
    start = as_server_time(datetime(2015, 1, 1))
    end = as_server_time(datetime(2015, 1, 2))
    resolution = timedelta(minutes=15)
    soc_at_start = battery.get_attribute("soc_in_mwh")
    schedule = schedule_battery(battery, start, end, resolution, soc_at_start)
    soc_schedule = integrate_time_series(schedule, soc_at_start, decimal_precision=6)

    with pd.option_context("display.max_rows", None, "display.max_columns", 3):
        print(soc_schedule)

    # Check if constraints were met
    assert (
        min(schedule.values) >= battery.get_attribute("capacity_in_mw") * -1 - TOLERANCE
    )
    assert max(schedule.values) <= battery.get_attribute("capacity_in_mw")
    for soc in soc_schedule.values:
        assert soc >= battery.get_attribute("min_soc_in_mwh")
        assert soc <= battery.get_attribute("max_soc_in_mwh")


@pytest.mark.parametrize(
    "roundtrip_efficiency",
    [
        1,
        0.99,
        0.01,
    ],
)
def test_battery_solver_day_2(add_battery_assets, roundtrip_efficiency: float):
    """Check battery scheduling results for day 2, which is set up with
    8 expensive, then 8 cheap, then again 8 expensive hours.
    If efficiency losses aren't too bad, we expect the scheduler to:
    - completely discharge within the first 8 hours
    - completely charge within the next 8 hours
    - completely discharge within the last 8 hours
    If efficiency losses are bad, the price difference is not worth cycling the battery,
    and so we expect the scheduler to only:
    - completely discharge within the last 8 hours
    """
    epex_da = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    battery = Sensor.query.filter(Sensor.name == "Test battery").one_or_none()
    assert Sensor.query.get(battery.get_attribute("market_id")) == epex_da
    start = as_server_time(datetime(2015, 1, 2))
    end = as_server_time(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    soc_at_start = battery.get_attribute("soc_in_mwh")
    soc_min = 0.5
    soc_max = 4.5
    schedule = schedule_battery(
        battery,
        start,
        end,
        resolution,
        soc_at_start,
        soc_min=soc_min,
        soc_max=soc_max,
        roundtrip_efficiency=roundtrip_efficiency,
    )
    soc_schedule = integrate_time_series(schedule, soc_at_start, decimal_precision=6)

    with pd.option_context("display.max_rows", None, "display.max_columns", 3):
        print(soc_schedule)

    # Check if constraints were met
    assert min(schedule.values) >= battery.get_attribute("capacity_in_mw") * -1
    assert max(schedule.values) <= battery.get_attribute("capacity_in_mw") + TOLERANCE
    for soc in soc_schedule.values:
        assert soc >= max(soc_min, battery.get_attribute("min_soc_in_mwh"))
        assert soc <= battery.get_attribute("max_soc_in_mwh")

    # Check whether the resulting soc schedule follows our expectations for 8 expensive, 8 cheap and 8 expensive hours
    assert soc_schedule.iloc[-1] == max(
        soc_min, battery.get_attribute("min_soc_in_mwh")
    )  # Battery sold out at the end of its planning horizon

    # As long as the roundtrip efficiency isn't too bad (I haven't computed the actual switch point)
    if roundtrip_efficiency > 0.9:
        assert soc_schedule.loc[start + timedelta(hours=8)] == max(
            soc_min, battery.get_attribute("min_soc_in_mwh")
        )  # Sell what you begin with
        assert soc_schedule.loc[start + timedelta(hours=16)] == min(
            soc_max, battery.get_attribute("max_soc_in_mwh")
        )  # Buy what you can to sell later
    else:
        # If the roundtrip efficiency is poor, best to stand idle
        assert soc_schedule.loc[start + timedelta(hours=8)] == battery.get_attribute(
            "soc_in_mwh"
        )
        assert soc_schedule.loc[start + timedelta(hours=16)] == battery.get_attribute(
            "soc_in_mwh"
        )


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
    or [0, 5] for a bidirectional station, given a charging capacity of 2 kW.
    """
    soc_at_start = 1
    duration_until_target = timedelta(hours=2)

    epex_da = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    charging_station = Sensor.query.filter(
        Sensor.name == charging_station_name
    ).one_or_none()
    assert charging_station.get_attribute("capacity_in_mw") == 2
    assert Sensor.query.get(charging_station.get_attribute("market_id")) == epex_da
    start = as_server_time(datetime(2015, 1, 2))
    end = as_server_time(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    target_soc_datetime = start + duration_until_target
    soc_targets = pd.Series(
        np.nan, index=pd.date_range(start, end, freq=resolution, closed="right")
    )
    soc_targets.loc[target_soc_datetime] = target_soc
    consumption_schedule = schedule_charging_station(
        charging_station, start, end, resolution, soc_at_start, soc_targets
    )
    soc_schedule = integrate_time_series(
        consumption_schedule, soc_at_start, decimal_precision=6
    )

    # Check if constraints were met
    assert (
        min(consumption_schedule.values)
        >= charging_station.get_attribute("capacity_in_mw") * -1
    )
    assert (
        max(consumption_schedule.values)
        <= charging_station.get_attribute("capacity_in_mw") + TOLERANCE
    )
    print(consumption_schedule.head(12))
    print(soc_schedule.head(12))
    assert abs(soc_schedule.loc[target_soc_datetime] - target_soc) < TOLERANCE


@pytest.mark.parametrize(
    "target_soc, charging_station_name",
    [
        (9, "Test charging station"),
        (15, "Test charging station"),
        (5, "Test charging station (bidirectional)"),
        (15, "Test charging station (bidirectional)"),
    ],
)
def test_fallback_to_unsolvable_problem(target_soc, charging_station_name):
    """Starting with a state of charge 10 kWh, within 2 hours we should be able to reach
    any state of charge in the range [10, 14] kWh for a unidirectional station,
    or [6, 14] for a bidirectional station, given a charging capacity of 2 kW.
    Here we test target states of charge outside that range, ones that we should be able
    to get as close to as 1 kWh difference.
    We want our scheduler to handle unsolvable problems like these with a sensible fallback policy.
    """
    soc_at_start = 10
    duration_until_target = timedelta(hours=2)
    expected_gap = 1

    epex_da = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    charging_station = Sensor.query.filter(
        Sensor.name == charging_station_name
    ).one_or_none()
    assert charging_station.get_attribute("capacity_in_mw") == 2
    assert Sensor.query.get(charging_station.get_attribute("market_id")) == epex_da
    start = as_server_time(datetime(2015, 1, 2))
    end = as_server_time(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    target_soc_datetime = start + duration_until_target
    soc_targets = pd.Series(
        np.nan, index=pd.date_range(start, end, freq=resolution, closed="right")
    )
    soc_targets.loc[target_soc_datetime] = target_soc
    consumption_schedule = schedule_charging_station(
        charging_station, start, end, resolution, soc_at_start, soc_targets
    )
    soc_schedule = integrate_time_series(
        consumption_schedule, soc_at_start, decimal_precision=6
    )

    # Check if constraints were met
    assert (
        min(consumption_schedule.values)
        >= charging_station.get_attribute("capacity_in_mw") * -1
    )
    assert max(consumption_schedule.values) <= charging_station.get_attribute(
        "capacity_in_mw"
    )
    print(consumption_schedule.head(12))
    print(soc_schedule.head(12))
    assert (
        abs(abs(soc_schedule.loc[target_soc_datetime] - target_soc) - expected_gap)
        < TOLERANCE
    )
