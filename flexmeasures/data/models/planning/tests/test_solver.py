from datetime import datetime, timedelta
import pytest
import pytz

import numpy as np
import pandas as pd

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.data.models.planning.utils import (
    ensure_storage_specs,
    initialize_series,
)
from flexmeasures.utils.calculations import integrate_time_series


TOLERANCE = 0.00001


@pytest.mark.parametrize("use_inflexible_device", [False, True])
def test_battery_solver_day_1(
    add_battery_assets, add_inflexible_device_forecasts, use_inflexible_device
):
    epex_da = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    battery = Sensor.query.filter(Sensor.name == "Test battery").one_or_none()
    assert battery.get_attribute("market_id") == epex_da.id
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 1))
    end = tz.localize(datetime(2015, 1, 2))
    resolution = timedelta(minutes=15)
    soc_at_start = battery.get_attribute("soc_in_mwh")
    storage_specs = ensure_storage_specs(
        dict(soc_at_start=soc_at_start), battery, start, end, resolution
    )
    schedule = StorageScheduler().schedule(
        battery,
        start,
        end,
        resolution,
        storage_specs=storage_specs,
        inflexible_device_sensors=add_inflexible_device_forecasts.keys()
        if use_inflexible_device
        else None,
    )
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
    assert battery.get_attribute("market_id") == epex_da.id
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    soc_at_start = battery.get_attribute("soc_in_mwh")
    soc_min = 0.5
    soc_max = 4.5
    storage_specs = ensure_storage_specs(
        dict(
            soc_at_start=soc_at_start,
            soc_min=soc_min,
            soc_max=soc_max,
            roundtrip_efficiency=roundtrip_efficiency,
        ),
        battery,
        start,
        end,
        resolution,
    )
    schedule = StorageScheduler().schedule(
        battery,
        start,
        end,
        resolution,
        storage_specs=storage_specs,
    )
    soc_schedule = integrate_time_series(
        schedule,
        soc_at_start,
        up_efficiency=roundtrip_efficiency**0.5,
        down_efficiency=roundtrip_efficiency**0.5,
        decimal_precision=6,
    )

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
    assert charging_station.get_attribute("market_id") == epex_da.id
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    target_soc_datetime = start + duration_until_target
    soc_targets = initialize_series(np.nan, start, end, resolution, inclusive="right")
    soc_targets.loc[target_soc_datetime] = target_soc
    storage_specs = ensure_storage_specs(
        dict(soc_at_start=soc_at_start, soc_targets=soc_targets),
        charging_station,
        start,
        end,
        resolution,
    )
    consumption_schedule = StorageScheduler().schedule(
        charging_station, start, end, resolution, storage_specs=storage_specs
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
    assert charging_station.get_attribute("market_id") == epex_da.id
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    target_soc_datetime = start + duration_until_target
    soc_targets = initialize_series(np.nan, start, end, resolution, inclusive="right")
    soc_targets.loc[target_soc_datetime] = target_soc
    storage_specs = ensure_storage_specs(
        dict(soc_at_start=soc_at_start, soc_targets=soc_targets),
        charging_station,
        start,
        end,
        resolution,
    )
    consumption_schedule = StorageScheduler().schedule(
        charging_station,
        start,
        end,
        resolution,
        storage_specs=storage_specs,
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


@pytest.mark.parametrize(
    "market_scenario",
    [
        "dynamic contract",
        "fixed contract",
    ],
)
def test_building_solver_day_2(
    db,
    add_battery_assets,
    add_market_prices,
    create_test_tariffs,
    add_inflexible_device_forecasts,
    inflexible_devices,
    flexible_devices,
    market_scenario: str,
):
    """Check battery scheduling results within the context of a building with PV, for day 2, against the following market scenarios:
    1) a dynamic tariff with equal consumption and feed-in tariffs, that is set up with 8 expensive, then 8 cheap, then again 8 expensive hours.
    2) a fixed consumption tariff and a fixed feed-in tariff that is lower.
    In the test data:
    - Hours with net production coincide with low dynamic market prices.
    - Hours with net consumption coincide with high dynamic market prices.
    In either scenario, we expect the scheduler to:
    - completely discharge within the first 8 hours (either due to 1) high prices, or 2) net consumption)
    - completely charge within the next 8 hours (either due to 1) low prices, or 2) net production)
    - completely discharge within the last 8 hours (either due to 1) high prices, or 2) net consumption)
    """
    battery = flexible_devices["battery power sensor"]
    building = battery.generic_asset
    if market_scenario == "dynamic contract":
        consumption_price_sensor = Sensor.query.filter(
            Sensor.name == "epex_da"
        ).one_or_none()
        production_price_sensor = consumption_price_sensor
        assert battery.get_attribute("market_id") == consumption_price_sensor.id
    elif market_scenario == "fixed contract":
        consumption_price_sensor = create_test_tariffs["consumption_price_sensor"]
        production_price_sensor = create_test_tariffs["production_price_sensor"]
    else:
        raise NotImplementedError(
            f"Missing test case for market conditions '{market_scenario}'"
        )
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    soc_at_start = 2.5
    soc_min = 0.5
    soc_max = 4.5
    storage_specs = ensure_storage_specs(
        dict(
            soc_at_start=soc_at_start,
            soc_min=soc_min,
            soc_max=soc_max,
        ),
        battery,
        start,
        end,
        resolution,
    )
    schedule = StorageScheduler().schedule(
        battery,
        start,
        end,
        resolution,
        storage_specs=storage_specs,
        inflexible_device_sensors=inflexible_devices.values(),
    )
    soc_schedule = integrate_time_series(schedule, soc_at_start, decimal_precision=6)

    with pd.option_context("display.max_rows", None, "display.max_columns", 3):
        print(soc_schedule)

    # Check if constraints were met
    capacity = pd.DataFrame(
        data=np.sum(np.array(list(add_inflexible_device_forecasts.values())), axis=0),
        columns=["inflexible"],
    ).tail(
        -4 * 24
    )  # remove first 96 quarter-hours (the schedule is about the 2nd day)
    capacity["max"] = building.get_attribute("capacity_in_mw")
    capacity["min"] = -building.get_attribute("capacity_in_mw")
    capacity["production headroom"] = capacity["max"] - capacity["inflexible"]
    capacity["consumption headroom"] = capacity["inflexible"] - capacity["min"]
    capacity["battery production headroom"] = capacity["production headroom"].clip(
        upper=battery.get_attribute("capacity_in_mw")
    )
    capacity["battery consumption headroom"] = capacity["consumption headroom"].clip(
        upper=battery.get_attribute("capacity_in_mw")
    )
    capacity[
        "schedule"
    ] = schedule.values  # consumption is positive, production is negative
    with pd.option_context(
        "display.max_rows", None, "display.max_columns", None, "display.width", 2000
    ):
        print(capacity)
    assert (capacity["schedule"] >= -capacity["battery production headroom"]).all()
    assert (capacity["schedule"] <= capacity["battery consumption headroom"]).all()

    for soc in soc_schedule.values:
        assert soc >= max(soc_min, battery.get_attribute("min_soc_in_mwh"))
        assert soc <= battery.get_attribute("max_soc_in_mwh")

    # Check whether the resulting soc schedule follows our expectations for:
    # 1) 8 expensive, 8 cheap and 8 expensive hours
    # 2) 8 net-consumption, 8 net-production and 8 net-consumption hours

    # 1) The battery sold out at the end of its planning horizon
    # 2) The battery discharged as far as it could during the last 8 net-consumption hours
    assert soc_schedule.iloc[-1] == max(
        soc_min, battery.get_attribute("min_soc_in_mwh")
    )

    # 1) Sell what you begin with
    # 2) The battery discharged as far as it could during the first 8 net-consumption hours
    assert soc_schedule.loc[start + timedelta(hours=8)] == max(
        soc_min, battery.get_attribute("min_soc_in_mwh")
    )

    # 1) Buy what you can to sell later
    # 2) The battery charged with PV power as far as it could during the middle 8 net-production hours
    assert soc_schedule.loc[start + timedelta(hours=16)] == min(
        soc_max, battery.get_attribute("max_soc_in_mwh")
    )
