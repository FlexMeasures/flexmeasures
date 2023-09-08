from datetime import datetime, timedelta
import pytest
import pytz

import numpy as np
import pandas as pd
from pandas.tseries.frequencies import to_offset

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.planning import Scheduler
from flexmeasures.data.models.planning.storage import (
    StorageScheduler,
    add_storage_constraints,
    validate_storage_constraints,
)
from flexmeasures.data.models.planning.linear_optimization import device_scheduler
from flexmeasures.data.models.planning.tests.utils import check_constraints
from flexmeasures.data.models.planning.utils import initialize_series, initialize_df
from flexmeasures.utils.calculations import (
    apply_stock_changes_and_losses,
    integrate_time_series,
)


TOLERANCE = 0.00001


@pytest.mark.parametrize(
    "initial_stock, stock_deltas, expected_stocks, storage_efficiency",
    [
        (
            1000,
            [100, -100, -100, 100],
            [1000, 1089, 979.11, 870.3189, 960.615711],
            0.99,
        ),
        (
            2.5,
            [-0.5, -0.5, -0.5, -0.5],
            [2.5, 1.8, 1.17, 0.603, 0.0927],
            0.9,
        ),
    ],
)
def test_storage_loss_function(
    initial_stock, stock_deltas, expected_stocks, storage_efficiency
):
    stocks = apply_stock_changes_and_losses(
        initial_stock,
        stock_deltas,
        storage_efficiency=storage_efficiency,
        how="left",
        decimal_precision=6,
    )
    print(stocks)
    assert all(a == b for a, b in zip(stocks, expected_stocks))


@pytest.mark.parametrize("use_inflexible_device", [False, True])
def test_battery_solver_day_1(
    add_battery_assets, add_inflexible_device_forecasts, use_inflexible_device
):
    epex_da, battery = get_sensors_from_db(add_battery_assets)
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 1))
    end = tz.localize(datetime(2015, 1, 2))
    resolution = timedelta(minutes=15)
    soc_at_start = battery.get_attribute("soc_in_mwh")
    scheduler: Scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={"soc-at-start": soc_at_start},
        flex_context={
            "inflexible-device-sensors": [
                s.id for s in add_inflexible_device_forecasts.keys()
            ]
            if use_inflexible_device
            else []
        },
    )
    schedule = scheduler.compute()

    # Check if constraints were met
    check_constraints(battery, schedule, soc_at_start)


@pytest.mark.parametrize(
    "roundtrip_efficiency, storage_efficiency",
    [
        (1, 1),
        (1, 0.999),
        (1, 0.5),
        (0.99, 1),
        (0.01, 1),
    ],
)
def test_battery_solver_day_2(
    add_battery_assets, roundtrip_efficiency: float, storage_efficiency: float
):
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
    _epex_da, battery = get_sensors_from_db(add_battery_assets)
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    soc_at_start = battery.get_attribute("soc_in_mwh")
    soc_min = 0.5
    soc_max = 4.5
    scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={
            "soc-at-start": soc_at_start,
            "soc-min": soc_min,
            "soc-max": soc_max,
            "roundtrip-efficiency": roundtrip_efficiency,
            "storage-efficiency": storage_efficiency,
        },
    )
    schedule = scheduler.compute()

    # Check if constraints were met
    soc_schedule = check_constraints(
        battery, schedule, soc_at_start, roundtrip_efficiency, storage_efficiency
    )

    # Check whether the resulting soc schedule follows our expectations for 8 expensive, 8 cheap and 8 expensive hours
    assert soc_schedule.iloc[-1] == max(
        soc_min, battery.get_attribute("min_soc_in_mwh")
    )  # Battery sold out at the end of its planning horizon

    # As long as the efficiencies aren't too bad (I haven't computed the actual switch points)
    if roundtrip_efficiency > 0.9 and storage_efficiency > 0.9:
        assert soc_schedule.loc[start + timedelta(hours=8)] == max(
            soc_min, battery.get_attribute("min_soc_in_mwh")
        )  # Sell what you begin with
        assert soc_schedule.loc[start + timedelta(hours=16)] == min(
            soc_max, battery.get_attribute("max_soc_in_mwh")
        )  # Buy what you can to sell later
    elif storage_efficiency > 0.9:
        # If only the roundtrip efficiency is poor, best to stand idle (keep a high SoC as long as possible)
        assert soc_schedule.loc[start + timedelta(hours=8)] == battery.get_attribute(
            "soc_in_mwh"
        )
        assert soc_schedule.loc[start + timedelta(hours=16)] == battery.get_attribute(
            "soc_in_mwh"
        )
    else:
        # If the storage efficiency is poor, regardless of whether the roundtrip efficiency is poor, best to sell asap
        assert soc_schedule.loc[start + timedelta(hours=8)] == max(
            soc_min, battery.get_attribute("min_soc_in_mwh")
        )
        assert soc_schedule.loc[start + timedelta(hours=16)] == max(
            soc_min, battery.get_attribute("min_soc_in_mwh")
        )


def run_test_charge_discharge_sign(
    battery,
    roundtrip_efficiency,
    consumption_price_sensor_id,
    production_price_sensor_id,
):
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 3))
    end = tz.localize(datetime(2015, 1, 4))
    resolution = timedelta(hours=1)
    storage_efficiency = 1
    # Choose the SoC constraints and starting value such that the battery can fully charge or discharge in a single time step
    soc_min = 0
    soc_max = battery.get_attribute("capacity_in_mw")
    soc_at_start = battery.get_attribute("capacity_in_mw")

    scheduler: Scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={
            "soc-min": soc_min,
            "soc-max": soc_max,
            "soc-at-start": soc_at_start,
            "roundtrip-efficiency": roundtrip_efficiency,
            "storage-efficiency": storage_efficiency,
            "prefer-charging-sooner": True,
        },
        flex_context={
            "consumption-price-sensor": consumption_price_sensor_id,
            "production-price-sensor": production_price_sensor_id,
        },
    )

    (
        sensor,
        start,
        end,
        resolution,
        soc_at_start,
        device_constraints,
        ems_constraints,
        commitment_quantities,
        commitment_downwards_deviation_price,
        commitment_upwards_deviation_price,
    ) = scheduler._prepare(skip_validation=True)

    _, _, results, model = device_scheduler(
        device_constraints,
        ems_constraints,
        commitment_quantities,
        commitment_downwards_deviation_price,
        commitment_upwards_deviation_price,
        initial_stock=soc_at_start * (timedelta(hours=1) / resolution),
    )

    device_power_sign = pd.Series(model.device_power_sign.extract_values())[0]
    device_power_up = pd.Series(model.device_power_up.extract_values())[0]
    device_power_down = pd.Series(model.device_power_down.extract_values())[0]

    is_power_down = ~np.isclose(abs(device_power_down), 0)
    is_power_up = ~np.isclose(abs(device_power_up), 0)

    # only one power active at a time
    assert (~(is_power_down & is_power_up)).all()

    # downwards power not active when the binary variable is 1
    assert (~is_power_down[device_power_sign == 1.0]).all()

    # upwards power not active when the binary variable is 0
    assert (~is_power_up[device_power_sign == 0.0]).all()

    schedule = initialize_series(
        data=[model.ems_power[0, j].value for j in model.j],
        start=start,
        end=end,
        resolution=to_offset(resolution),
    )

    # Check if constraints were met
    soc_schedule = check_constraints(
        battery, schedule, soc_at_start, roundtrip_efficiency, storage_efficiency
    )

    return schedule.tz_convert(tz), soc_schedule.tz_convert(tz)


def test_battery_solver_day_3(
    add_battery_assets,
    add_inflexible_device_forecasts,
):
    """Check battery scheduling results for day 3, which is set up with
    8 hours with negative prices, followed by 16 expensive hours.

    Under certain conditions, batteries can be used to "burn" energy in form of heat, due to the conversion
    losses of the inverters. Nonetheless, this doesn't come for free as this is shortening the lifetime of the asset.
    For this reason, the constraints `device_up_derivative_sign` and `device_down_derivative_sign' make sure that
    the storage can only charge or discharge within the same time period.

    These constraints don't avoid burning energy in Case 1) in which a storage with conversion losses operating under the
    same buy/sell prices.

    Nonetheless, as shown in Cases 3) and 4), the oscillatory dynamic is gone when having Consumption Price > Production Price.
    This is because even though the energy consumed is bigger than that produced, the difference between the cost of consuming and the
    revenue of producing doesn't create a profit.
    """

    roundtrip_efficiency = 0.9
    epex_da = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    epex_da_production = Sensor.query.filter(
        Sensor.name == "epex_da_production"
    ).one_or_none()
    battery = add_battery_assets["Test battery"].sensors[0]

    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 3))

    # Case 1: Consumption Price = Production Price, roundtrip_efficiency < 1
    schedule_1, soc_schedule_1 = run_test_charge_discharge_sign(
        battery, roundtrip_efficiency, epex_da.id, epex_da.id
    )

    # For the negative price period, the schedule shows oscillations
    # discharge in even hours
    assert all(schedule_1[:8:2] < 0)  # 12am, 2am, 4am, 6am

    # charge in odd hours
    assert all(schedule_1[1:8:2] > 0)  # 1am, 3am, 5am, 7am

    # in positive price hours, the battery will only discharge to sell the energy charged in the negative hours
    assert all(schedule_1.loc[start + timedelta(hours=8) :] <= 0)

    # Case 2: Consumption Price = Production Price, roundtrip_efficiency = 1
    schedule_2, soc_schedule_2 = run_test_charge_discharge_sign(
        battery, 1, epex_da.id, epex_da.id
    )
    assert all(np.isclose(schedule_2[:8], 0))  # no oscillation

    # Case 3: Consumption Price > Production Price, roundtrip_efficiency < 1
    # In this case, we expect the battery to hold the energy that has initially and sell it during the period of
    # positive prices.
    schedule_3, soc_schedule_3 = run_test_charge_discharge_sign(
        battery, roundtrip_efficiency, epex_da.id, epex_da_production.id
    )
    assert all(np.isclose(schedule_3[:8], 0))  # no oscillation
    assert all(schedule_3[8:] <= 0)

    # discharge the whole battery in 1 time period
    assert np.isclose(
        schedule_3.min(),
        -battery.get_attribute("capacity_in_mw") * np.sqrt(roundtrip_efficiency),
    )

    # Case 4: Consumption Price > Production Price, roundtrip_efficiency < 1
    schedule_4, soc_schedule_4 = run_test_charge_discharge_sign(
        battery, 1, epex_da.id, epex_da_production.id
    )

    assert all(np.isclose(schedule_4[:8], 0))  # no oscillation
    assert all(schedule_4[8:] <= 0)

    # discharge the whole battery in 1 time period, with no conversion losses
    assert np.isclose(schedule_4.min(), -battery.get_attribute("capacity_in_mw"))


@pytest.mark.parametrize(
    "target_soc, charging_station_name",
    [
        (1, "Test charging station"),
        (5, "Test charging station"),
        (0, "Test charging station (bidirectional)"),
        (5, "Test charging station (bidirectional)"),
    ],
)
def test_charging_station_solver_day_2(
    target_soc, charging_station_name, setup_planning_test_data
):
    """Starting with a state of charge 1 kWh, within 2 hours we should be able to reach
    any state of charge in the range [1, 5] kWh for a unidirectional station,
    or [0, 5] for a bidirectional station, given a charging capacity of 2 kW.
    """
    soc_at_start = 1
    duration_until_target = timedelta(hours=2)

    epex_da = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    charging_station = setup_planning_test_data[charging_station_name].sensors[0]
    assert charging_station.get_attribute("capacity_in_mw") == 2
    assert charging_station.get_attribute("market_id") == epex_da.id
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    target_soc_datetime = start + duration_until_target
    soc_targets = initialize_series(np.nan, start, end, resolution, inclusive="right")
    soc_targets.loc[target_soc_datetime] = target_soc
    scheduler = StorageScheduler(
        charging_station,
        start,
        end,
        resolution,
        flex_model={
            "soc_at_start": soc_at_start,
            "soc_min": charging_station.get_attribute("min_soc_in_mwh", 0),
            "soc_max": charging_station.get_attribute(
                "max_soc_in_mwh", max(soc_targets.values)
            ),
            "roundtrip_efficiency": charging_station.get_attribute(
                "roundtrip_efficiency", 1
            ),
            "storage_efficiency": charging_station.get_attribute(
                "storage_efficiency", 1
            ),
            "soc_targets": soc_targets,
        },
    )
    scheduler.config_deserialized = (
        True  # soc targets are already a DataFrame, names get underscore
    )
    consumption_schedule = scheduler.compute()
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
def test_fallback_to_unsolvable_problem(
    target_soc, charging_station_name, setup_planning_test_data
):
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
    charging_station = setup_planning_test_data[charging_station_name].sensors[0]
    assert charging_station.get_attribute("capacity_in_mw") == 2
    assert charging_station.get_attribute("market_id") == epex_da.id
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    target_soc_datetime = start + duration_until_target
    soc_targets = initialize_series(np.nan, start, end, resolution, inclusive="right")
    soc_targets.loc[target_soc_datetime] = target_soc
    scheduler = StorageScheduler(
        charging_station,
        start,
        end,
        resolution,
        flex_model={
            "soc_at_start": soc_at_start,
            "soc_min": charging_station.get_attribute("min_soc_in_mwh", 0),
            "soc_max": charging_station.get_attribute(
                "max_soc_in_mwh", max(soc_targets.values)
            ),
            "roundtrip_efficiency": charging_station.get_attribute(
                "roundtrip_efficiency", 1
            ),
            "storage_efficiency": charging_station.get_attribute(
                "storage_efficiency", 1
            ),
            "soc_targets": soc_targets,
        },
    )
    scheduler.config_deserialized = (
        True  # soc targets are already a DataFrame, names get underscore
    )
    consumption_schedule = scheduler.compute(skip_validation=True)
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
    2) a fixed consumption tariff and a fixed feed-in tariff that is lower, which incentives to maximize self-consumption of PV power into the battery.
    In the test data:
    - Hours with net production coincide with low dynamic market prices.
    - Hours with net consumption coincide with high dynamic market prices.
    So when the prices are low (in scenario 1), we have net production, and when they are high, net consumption.
    That means we have first net consumption, then net production, and then net consumption again.
    In either scenario, we expect the scheduler to:
    - completely discharge within the first 8 hours (either due to 1) high prices, or 2) net consumption)
    - completely charge within the next 8 hours (either due to 1) low prices, or 2) net production)
    - completely discharge within the last 8 hours (either due to 1) high prices, or 2) net consumption)
    """
    battery = flexible_devices["battery power sensor"]
    building = battery.generic_asset
    default_consumption_price_sensor = Sensor.query.filter(
        Sensor.name == "epex_da"
    ).one_or_none()
    assert battery.get_attribute("market_id") == default_consumption_price_sensor.id
    if market_scenario == "dynamic contract":
        consumption_price_sensor = default_consumption_price_sensor
        production_price_sensor = consumption_price_sensor
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
    scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={
            "soc_at_start": soc_at_start,
            "soc_min": soc_min,
            "soc_max": soc_max,
            "roundtrip_efficiency": battery.get_attribute("roundtrip_efficiency", 1),
            "storage_efficiency": battery.get_attribute("storage_efficiency", 1),
        },
        flex_context={
            "inflexible_device_sensors": inflexible_devices.values(),
            "production_price_sensor": production_price_sensor,
            "consumption_price_sensor": consumption_price_sensor,
        },
    )
    scheduler.config_deserialized = (
        True  # inflexible device sensors are already objects, names get underscore
    )
    schedule = scheduler.compute()
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

    # Check whether the resulting soc schedule follows our expectations for.
    # To recap, in scenario 1 and 2, the schedule should mainly be influenced by:
    # 1) 8 expensive, 8 cheap and 8 expensive hours
    # 2) 8 net-consumption, 8 net-production and 8 net-consumption hours

    # Result after 8 hours
    # 1) Sell what you begin with
    # 2) The battery discharged as far as it could during the first 8 net-consumption hours
    assert soc_schedule.loc[start + timedelta(hours=8)] == max(
        soc_min, battery.get_attribute("min_soc_in_mwh")
    )

    # Result after second 8 hour-interval
    # 1) Buy what you can to sell later, when prices will be high again
    # 2) The battery charged with PV power as far as it could during the middle 8 net-production hours
    assert soc_schedule.loc[start + timedelta(hours=16)] == min(
        soc_max, battery.get_attribute("max_soc_in_mwh")
    )

    # Result at end of day
    # 1) The battery sold out at the end of its planning horizon
    # 2) The battery discharged as far as it could during the last 8 net-consumption hours
    assert soc_schedule.iloc[-1] == max(
        soc_min, battery.get_attribute("min_soc_in_mwh")
    )


def test_soc_bounds_timeseries(add_battery_assets):
    """Check that the maxima and minima timeseries alter the result
    of the optimization.

    Two schedules are run:
    - with global maximum and minimum values
    - with global maximum and minimum values +  maxima / minima time series constraints
    """

    # get the sensors from the database
    epex_da, battery = get_sensors_from_db(add_battery_assets)

    # time parameters
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(hours=1)

    # soc parameters
    soc_at_start = battery.get_attribute("soc_in_mwh")
    soc_min = 0.5
    soc_max = 4.5

    def compute_schedule(flex_model):
        scheduler = StorageScheduler(
            battery,
            start,
            end,
            resolution,
            flex_model=flex_model,
        )
        schedule = scheduler.compute()

        soc_schedule = integrate_time_series(
            schedule,
            soc_at_start,
            decimal_precision=6,
        )

        return soc_schedule

    flex_model = {
        "soc-at-start": soc_at_start,
        "soc-min": soc_min,
        "soc-max": soc_max,
    }

    soc_schedule_1 = compute_schedule(flex_model)

    # soc maxima and soc minima
    soc_maxima = [
        {"datetime": "2015-01-02T15:00:00+01:00", "value": 1.0},
        {"datetime": "2015-01-02T16:00:00+01:00", "value": 1.0},
    ]

    soc_minima = [{"datetime": "2015-01-02T08:00:00+01:00", "value": 3.5}]

    soc_targets = [{"datetime": "2015-01-02T19:00:00+01:00", "value": 2.0}]

    flex_model = {
        "soc-at-start": soc_at_start,
        "soc-min": soc_min,
        "soc-max": soc_max,
        "soc-maxima": soc_maxima,
        "soc-minima": soc_minima,
        "soc-targets": soc_targets,
    }

    soc_schedule_2 = compute_schedule(flex_model)

    # check that, in this case, adding the constraints
    # alter the SOC profile
    assert not soc_schedule_2.equals(soc_schedule_1)

    # check that global minimum is achieved
    assert soc_schedule_1.min() == soc_min
    assert soc_schedule_2.min() == soc_min

    # check that global maximum is achieved
    assert soc_schedule_1.max() == soc_max
    assert soc_schedule_2.max() == soc_max

    # test for soc_minima
    # check that the local minimum constraint is respected
    assert soc_schedule_2.loc["2015-01-02T08:00:00+01:00"] >= 3.5

    # test for soc_maxima
    # check that the local maximum constraint is respected
    assert soc_schedule_2.loc["2015-01-02T15:00:00+01:00"] <= 1.0

    # test for soc_targets
    # check that the SOC target (at 19 pm, local time) is met
    assert soc_schedule_2.loc["2015-01-02T19:00:00+01:00"] == 2.0


@pytest.mark.parametrize(
    "value_soc_min, value_soc_minima, value_soc_target, value_soc_maxima, value_soc_max",
    [
        (-1, -0.5, 0, 0.5, 1.0),
        (-1, -2, 0, 0.5, 1.0),
        (-1, -0.5, 0.5, 0.5, 1.0),
    ],
)
def test_add_storage_constraints(
    value_soc_min, value_soc_minima, value_soc_target, value_soc_maxima, value_soc_max
):
    """Check that the storage constraints are generated properly"""

    # from 00:00 to 04.00, both inclusive.
    start = datetime(2023, 5, 18, tzinfo=pytz.utc)
    end = datetime(2023, 5, 18, 5, tzinfo=pytz.utc)
    # hourly resolution
    resolution = timedelta(hours=1)

    soc_at_start = 0.0

    test_date = start + timedelta(hours=1)

    soc_targets = initialize_series(np.nan, start, end, resolution)
    soc_targets[test_date] = value_soc_target

    soc_maxima = initialize_series(np.nan, start, end, resolution)
    soc_maxima[test_date] = value_soc_maxima

    soc_minima = initialize_series(np.nan, start, end, resolution)
    soc_minima[test_date] = value_soc_minima

    soc_max = value_soc_max
    soc_min = value_soc_min

    storage_device_constraints = add_storage_constraints(
        start,
        end,
        resolution,
        soc_at_start,
        soc_targets,
        soc_maxima,
        soc_minima,
        soc_max,
        soc_min,
    )

    assert (storage_device_constraints["max"] <= soc_max).all()
    assert (storage_device_constraints["min"] >= soc_min).all()

    equals_not_nan = ~storage_device_constraints["equals"].isna()

    assert (storage_device_constraints["min"] <= storage_device_constraints["equals"])[
        equals_not_nan
    ].all()
    assert (storage_device_constraints["equals"] <= storage_device_constraints["max"])[
        equals_not_nan
    ].all()


@pytest.mark.parametrize(
    "value_min1, value_equals1, value_max1, value_min2, value_equals2, value_max2, expected_constraint_type_violations",
    [
        (1, np.nan, 9, 1, np.nan, 9, []),  # base case
        (1, np.nan, 10, 1, np.nan, 10, []),  # exact equality
        (
            1,
            np.nan,
            10 + 0.5e-6,
            1,
            np.nan,
            10,
            [],
        ),  # equality considering the precision (6 decimal figures)
        (
            1,
            np.nan,
            10 + 1e-5,
            1,
            np.nan,
            10,
            ["max(t) <= soc_max(t)"],
        ),  # difference of 0.5e-5 > 1e-6
        (1, np.nan, 9, 2, np.nan, 20, ["max(t) <= soc_max(t)"]),
        (-1, np.nan, 9, 1, np.nan, 9, ["soc_min(t) <= min(t)"]),
        (1, 10, 9, 1, np.nan, 9, ["equals(t) <= max(t)"]),
        (1, 0, 9, 1, np.nan, 9, ["min(t) <= equals(t)"]),
        (
            1,
            np.nan,
            9,
            9,
            np.nan,
            1,
            ["min(t) <= max(t)"],
        ),
        (
            9,
            5,
            1,
            1,
            np.nan,
            9,
            ["min(t) <= equals(t)", "equals(t) <= max(t)", "min(t) <= max(t)"],
        ),
        (1, np.nan, 9, 1, np.nan, 9, []),  # same interval, should not fail
        (1, np.nan, 9, 3, np.nan, 7, []),  # should not fail, containing interval
        (1, np.nan, 3, 3, np.nan, 5, []),  # difference = 0 < 1, should not fail
        (1, np.nan, 3, 4, np.nan, 5, []),  # difference == max, should not fail
        (
            1,
            np.nan,
            3,
            5,
            np.nan,
            7,
            ["min(t) - max(t-1) <= derivative_max(t) * factor_w_wh(t)"],
        ),  # difference > max = 1, this should fail
        (3, np.nan, 5, 2, np.nan, 3, []),  # difference = 0 < 1, should not fail
        (3, np.nan, 5, 1, np.nan, 2, []),  # difference = -1 >= -1, should not fail
        (
            3,
            np.nan,
            5,
            1,
            np.nan,
            1,
            ["derivative_min(t) * factor_w_wh(t) <= max(t) - min(t-1)"],
        ),  # difference = -2 < -1, should fail,
        (1, 4, 9, 1, 4, 9, []),  # same target value (4), should not fail
        (
            1,
            6,
            9,
            1,
            4,
            9,
            ["derivative_min(t) * factor_w_wh(t) <= equals(t) - equals(t-1)"],
        ),  # difference = -2 < -1, should fail,
        (
            1,
            4,
            9,
            1,
            6,
            9,
            ["equals(t) - equals(t-1) <= derivative_max(t) * factor_w_wh(t)"],
        ),  # difference 2 > 1, should fail,
    ],
)
def test_validate_constraints(
    value_min1,
    value_equals1,
    value_max1,
    value_min2,
    value_equals2,
    value_max2,
    expected_constraint_type_violations,
):
    """Check the validation of constraints.
    Two consecutive SOC ranges are parametrized (min, equals, max) and the different conditions are tested.
    """
    # from 00:00 to 04.00, both inclusive.
    start = datetime(2023, 5, 18, tzinfo=pytz.utc)
    end = datetime(2023, 5, 18, 5, tzinfo=pytz.utc)

    # hourly resolution
    resolution = timedelta(hours=1)

    columns = ["equals", "max", "min", "derivative max", "derivative min"]

    storage_device_constraints = initialize_df(columns, start, end, resolution)

    test_time = start + resolution * 2

    storage_device_constraints["min"] = 0
    storage_device_constraints["max"] = 10

    storage_device_constraints["derivative max"] = 1
    storage_device_constraints["derivative min"] = -1

    storage_device_constraints.loc[
        storage_device_constraints.index == test_time, "min"
    ] = value_min1
    storage_device_constraints.loc[
        storage_device_constraints.index == test_time, "max"
    ] = value_max1
    storage_device_constraints.loc[
        storage_device_constraints.index == test_time, "equals"
    ] = value_equals1

    storage_device_constraints.loc[
        storage_device_constraints.index == test_time + resolution, "min"
    ] = value_min2
    storage_device_constraints.loc[
        storage_device_constraints.index == test_time + resolution, "max"
    ] = value_max2
    storage_device_constraints.loc[
        storage_device_constraints.index == test_time + resolution, "equals"
    ] = value_equals2

    constraint_violations = validate_storage_constraints(
        constraints=storage_device_constraints,
        soc_at_start=0.0,
        soc_min=0,
        soc_max=10,
        resolution=resolution,
    )

    constraint_type_violations_output = set(
        constraint_violation["condition"]
        for constraint_violation in constraint_violations
    )

    assert set(expected_constraint_type_violations) == constraint_type_violations_output


def test_infeasible_problem_error(add_battery_assets):
    """Try to create a schedule with infeasible constraints. soc-max is 4.5 and soc-target is 8.0"""

    # get the sensors from the database
    _epex_da, battery = get_sensors_from_db(add_battery_assets)

    # time parameters
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(hours=1)

    def compute_schedule(flex_model):
        scheduler = StorageScheduler(
            battery,
            start,
            end,
            resolution,
            flex_model=flex_model,
        )
        schedule = scheduler.compute()

        soc_schedule = integrate_time_series(
            schedule,
            soc_at_start,
            decimal_precision=1,
        )

        return soc_schedule

    # soc parameters
    soc_at_start = battery.get_attribute("soc_in_mwh")
    infeasible_max_soc_targets = [
        {"datetime": "2015-01-02T16:00:00+01:00", "value": 8.0}
    ]

    flex_model = {
        "soc-at-start": soc_at_start,
        "soc-min": 0.5,
        "soc-max": 4.5,
        "soc-targets": infeasible_max_soc_targets,
    }

    with pytest.raises(
        ValueError, match="The input data yields an infeasible problem."
    ):
        compute_schedule(flex_model)


def get_sensors_from_db(battery_assets):
    # get the sensors from the database
    epex_da = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    battery = battery_assets["Test battery"].sensors[0]
    assert battery.get_attribute("market_id") == epex_da.id

    return epex_da, battery


@pytest.mark.parametrize("solver", ["appsi_highs", "cbc"])
def test_numerical_errors(app, setup_planning_test_data, solver):
    """Test that a soc-target = soc-max can exceed this value due to numerical errors in the operations
    to compute the device constraint DataFrame.
    In the case of HiGHS, the tiny difference creates an infeasible constraint.
    """

    epex_da = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    charging_station = setup_planning_test_data[
        "Test charging station (bidirectional)"
    ].sensors[0]
    assert charging_station.get_attribute("capacity_in_mw") == 2
    assert charging_station.get_attribute("market_id") == epex_da.id

    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(minutes=5)

    duration_until_next_target = timedelta(hours=1)
    target_soc_datetime_1 = pd.Timestamp(start + duration_until_next_target).isoformat()
    target_soc_datetime_2 = pd.Timestamp(
        start + 2 * duration_until_next_target
    ).isoformat()

    # select which solver to use
    app.config["FLEXMEASURES_LP_SOLVER"] = solver

    scheduler = StorageScheduler(
        charging_station,
        start,
        end,
        resolution,
        flex_model={
            "soc-at-start": 0.01456,
            "soc-min": 0.01295,
            "soc-max": 0.056,
            "roundtrip-efficiency": 0.85,
            "storage-efficiency": 1,
            "soc-targets": [
                {"value": 0.01295, "datetime": target_soc_datetime_1},
                {"value": 0.056, "datetime": target_soc_datetime_2},
            ],
            "soc-unit": "MWh",
        },
    )

    (
        sensor,
        start,
        end,
        resolution,
        soc_at_start,
        device_constraints,
        ems_constraints,
        commitment_quantities,
        commitment_downwards_deviation_price,
        commitment_upwards_deviation_price,
    ) = scheduler._prepare(skip_validation=True)

    _, _, results, model = device_scheduler(
        device_constraints,
        ems_constraints,
        commitment_quantities,
        commitment_downwards_deviation_price,
        commitment_upwards_deviation_price,
        initial_stock=soc_at_start * (timedelta(hours=1) / resolution),
    )

    assert device_constraints[0]["equals"].max() > device_constraints[0]["max"].max()
    assert device_constraints[0]["equals"].min() < device_constraints[0]["min"].min()
    assert results.solver.status == "ok"
