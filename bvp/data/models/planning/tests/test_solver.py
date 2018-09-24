from datetime import datetime, timedelta

import pandas as pd

from bvp.data.models.assets import Asset
from bvp.data.models.markets import Market
from bvp.data.models.planning.battery import schedule_battery
from bvp.utils.time_utils import as_bvp_time


def test_battery_solver_day_1():
    epex_da = Market.query.filter(Market.name == "epex_da").one_or_none()
    battery = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    start = as_bvp_time(datetime(2015, 1, 1))
    end = as_bvp_time(datetime(2015, 1, 2))
    resolution = timedelta(minutes=15)
    schedule = schedule_battery(battery, epex_da, start, end, resolution)
    print(schedule)

    # Check if constraints were met
    assert min(schedule.values) >= battery.capacity_in_mw * -1
    assert max(schedule.values) <= battery.capacity_in_mw
    cum_value = battery.soc_in_mwh
    for value in schedule.values:
        cum_value += value
        assert cum_value >= battery.min_soc_in_mwh
        assert cum_value <= battery.max_soc_in_mwh


def test_battery_solver_day_2():
    epex_da = Market.query.filter(Market.name == "epex_da").one_or_none()
    battery = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    start = as_bvp_time(datetime(2015, 1, 2))
    end = as_bvp_time(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)
    schedule = schedule_battery(battery, epex_da, start, end, resolution)

    with pd.option_context("display.max_rows", None, "display.max_columns", 3):
        print(schedule)

    # Check if constraints were met
    assert min(schedule.values) >= battery.capacity_in_mw * -1
    assert max(schedule.values) <= battery.capacity_in_mw
    cum_value = battery.soc_in_mwh
    for value in schedule.values:
        cum_value += value
        assert cum_value >= battery.min_soc_in_mwh
        assert cum_value <= battery.max_soc_in_mwh

    # Check whether the resulting schedule follows our expectations for 8 expensive, 8 cheap and 8 expensive hours
    assert cum_value == 0  # Battery sold out at the end of its planning horizon
    assert (
        sum(schedule.loc[start : start + timedelta(hours=8) - resolution].values)
        == battery.soc_in_mwh * -1
    )  # Sell what you begin with
    assert (
        sum(
            schedule.loc[
                start + timedelta(hours=8) : start + timedelta(hours=16) - resolution
            ].values
        )
        == battery.max_soc_in_mwh
    )  # Buy what you can to sell later
    assert (
        sum(schedule.loc[start + timedelta(hours=16) : end - resolution].values)
        == battery.max_soc_in_mwh * -1
    )  # Sell off everything
