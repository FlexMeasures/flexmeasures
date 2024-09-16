from datetime import datetime, timedelta
import pytest
import pytz

from flexmeasures.data.models.planning.process import ProcessScheduler
from flexmeasures.tests.utils import get_test_sensor


tz = pytz.timezone("Europe/Amsterdam")
start = tz.localize(datetime(2015, 1, 2))
end = tz.localize(datetime(2015, 1, 3))
resolution = timedelta(hours=1)


@pytest.mark.parametrize(
    "process_type, optimal_start",
    [("INFLEXIBLE", datetime(2015, 1, 2, 0)), ("SHIFTABLE", datetime(2015, 1, 2, 8))],
)
def test_process_scheduler(
    add_battery_assets, process, process_type, optimal_start, db
):
    """
    Test scheduling a process of 4kW of power that last 4h using the ProcessScheduler
    without time restrictions.
    """

    # get the sensors from the database
    epex_da = get_test_sensor(db)

    flex_model = {
        "duration": "PT4H",
        "process-type": process_type,
        "power": 4,
    }

    flex_context = {
        "consumption-price-sensor": epex_da.id,
    }

    scheduler = ProcessScheduler(
        process,
        start,
        end,
        resolution,
        flex_model=flex_model,
        flex_context=flex_context,
    )
    schedule = scheduler.compute()

    optimal_start = tz.localize(optimal_start)

    mask = (optimal_start <= schedule.index) & (
        schedule.index < optimal_start + timedelta(hours=4)
    )

    assert (schedule[mask] == 4).all()
    assert (schedule[~mask] == 0).all()


@pytest.mark.parametrize(
    "process_type, optimal_start",
    [("INFLEXIBLE", datetime(2015, 1, 2, 0)), ("SHIFTABLE", datetime(2015, 1, 2, 8))],
)
def test_duration_exceeds_planning_window(
    add_battery_assets, process, process_type, optimal_start, db
):
    """
    Test scheduling a process that last longer than the planning window.
    """

    # get the sensors from the database
    epex_da = get_test_sensor(db)

    flex_model = {
        "duration": "PT48H",
        "process-type": process_type,
        "power": 4,
    }

    flex_context = {
        "consumption-price-sensor": epex_da.id,
    }

    scheduler = ProcessScheduler(
        process,
        start,
        end,
        resolution,
        flex_model=flex_model,
        flex_context=flex_context,
    )
    schedule = scheduler.compute()

    optimal_start = tz.localize(optimal_start)

    assert (schedule == 4).all()


def test_process_scheduler_time_restrictions(add_battery_assets, process, db):
    """
    Test ProcessScheduler with a time restrictions consisting of a block of 2h starting
    at 8am. The resulting schedules avoid the 8am-10am period and schedules for a valid period.
    """

    # get the sensors from the database
    epex_da = get_test_sensor(db)

    # time parameters

    flex_model = {
        "duration": "PT4H",
        "process-type": "SHIFTABLE",
        "power": 4,
        "time-restrictions": [
            {"start": "2015-01-02T08:00:00+01:00", "duration": "PT2H"}
        ],
    }
    flex_context = {
        "consumption-price-sensor": epex_da.id,
    }

    scheduler = ProcessScheduler(
        process,
        start,
        end,
        resolution,
        flex_model=flex_model,
        flex_context=flex_context,
    )
    schedule = scheduler.compute()

    optimal_start = tz.localize(datetime(2015, 1, 2, 10))

    mask = (optimal_start <= schedule.index) & (
        schedule.index < optimal_start + timedelta(hours=4)
    )

    assert (schedule[mask] == 4).all()
    assert (schedule[~mask] == 0).all()

    # check that the time restrictions are fulfilled
    time_restrictions = scheduler.flex_model["time_restrictions"]
    time_restrictions = time_restrictions.tz_convert(tz)

    assert (schedule[time_restrictions] == 0).all()


def test_breakable_scheduler_time_restrictions(add_battery_assets, process, db):
    """
    Test BREAKABLE process_type of ProcessScheduler by introducing four 1-hour restrictions
    interspaced by 1 hour. The equivalent mask would be the following: [0,...,0,1,0,1,0,1,0,1,0, ...,0].
    Trying to get the best prices (between 9am and 4pm), his makes the schedule choose time periods between
    the time restrictions.
    """

    # get the sensors from the database
    epex_da = get_test_sensor(db)

    # time parameters

    flex_model = {
        "duration": "PT4H",
        "process-type": "BREAKABLE",
        "power": 4,
        "time-restrictions": [
            {"start": "2015-01-02T09:00:00+01:00", "duration": "PT1H"},
            {"start": "2015-01-02T11:00:00+01:00", "duration": "PT1H"},
            {"start": "2015-01-02T13:00:00+01:00", "duration": "PT1H"},
            {"start": "2015-01-02T15:00:00+01:00", "duration": "PT1H"},
        ],
    }

    flex_context = {
        "consumption-price-sensor": epex_da.id,
    }

    scheduler = ProcessScheduler(
        process,
        start,
        end,
        resolution,
        flex_model=flex_model,
        flex_context=flex_context,
    )
    schedule = scheduler.compute()

    expected_schedule = [0] * 8 + [4, 0, 4, 0, 4, 0, 4, 0] + [0] * 8

    assert (schedule == expected_schedule).all()

    # check that the time restrictions are fulfilled
    time_restrictions = scheduler.flex_model["time_restrictions"]
    time_restrictions = time_restrictions.tz_convert(tz)

    assert (schedule[time_restrictions] == 0).all()


@pytest.mark.parametrize(
    "process_type, time_restrictions",
    [
        ("BREAKABLE", [{"start": "2015-01-02T00:00:00+01:00", "duration": "PT24H"}]),
        ("INFLEXIBLE", [{"start": "2015-01-02T03:00:00+01:00", "duration": "PT21H"}]),
        ("SHIFTABLE", [{"start": "2015-01-02T03:00:00+01:00", "duration": "PT21H"}]),
    ],
)
def test_impossible_schedules(
    add_battery_assets, process, process_type, time_restrictions, db
):
    """
    Test schedules with time restrictions that make a 4h block not fit anytime during the
    planned window.
    """

    # get the sensors from the database
    epex_da = get_test_sensor(db)

    flex_model = {
        "duration": "PT4H",
        "process-type": process_type,
        "power": 4,
        "time-restrictions": time_restrictions,
    }
    flex_context = {
        "consumption-price-sensor": epex_da.id,
    }

    scheduler = ProcessScheduler(
        process,
        start,
        end,
        resolution,
        flex_model=flex_model,
        flex_context=flex_context,
    )

    with pytest.raises(ValueError):
        scheduler.compute()
