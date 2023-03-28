from datetime import datetime, timedelta
import copy
import logging

import pytz
import pytest

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.tests.utils import work_on_rq, exception_reporter
from flexmeasures.data.services.scheduling import create_scheduling_job
from flexmeasures.data.services.utils import hash_function_arguments


@pytest.mark.parametrize(
    "args_modified,kwargs_modified,equal",
    [
        (
            [1, 2, "1"],
            {
                "key1": "value1",
                "key2": "value2",
                "key3": 3,
                "key4": {"key1_nested": 1, "key2_nested": 2},
            },
            True,
        ),
        (
            [1, 2, 1],
            {
                "key1": "value1",
                "key2": "value2",
                "key3": 3,
                "key4": {"key1_nested": 1, "key2_nested": 2},
            },
            False,
        ),
        (
            [1, 2, "1"],
            {
                "key1": "different",
                "key2": "value2",
                "key3": 3,
                "key4": {"key1_nested": 1, "key2_nested": 2},
            },
            False,
        ),
        (
            [1, 2, "1"],
            {
                "different": "value1",
                "key2": "value2",
                "key3": 3,
                "key4": {"key1_nested": 1, "key2_nested": 2},
            },
            False,
        ),
        (
            [1, 2, "1"],
            {
                "key1": "value1",
                "key2": "value2",
                "key3": 3,
                "key4": {"key1_nested": "different", "key2_nested": 2},
            },
            False,
        ),
    ],
)
def test_hashing_simple(args_modified: list, kwargs_modified: dict, equal: bool):
    args = [1, 2, "1"]
    kwargs = {
        "key1": "value1",
        "key2": "value2",
        "key3": 3,
        "key4": {"key1_nested": 1, "key2_nested": 2},
    }

    hash_original = hash_function_arguments(args, kwargs)
    hash_modified = hash_function_arguments(args_modified, kwargs_modified)

    if equal:
        assert hash_original == hash_modified
    else:
        assert hash_original != hash_modified


def test_hashing(db, app, add_charging_station_assets, setup_test_data):
    soc_at_start = 1
    target_soc = 5
    duration_until_target = timedelta(hours=2)

    charging_station = Sensor.query.filter(
        Sensor.name == "Test charging station"
    ).one_or_none()
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    target_datetime = start + duration_until_target
    resolution = timedelta(minutes=15)
    soc_targets = [dict(datetime=target_datetime.isoformat(), value=target_soc)]

    kwargs = dict(
        sensor=charging_station,
        start=start,
        end=end,
        belief_time=start,
        resolution=resolution,
        flex_model={"soc-at-start": soc_at_start, "soc-targets": soc_targets},
    )
    args = []

    hash = hash_function_arguments(args, kwargs)
    print(hash)
    # checks that hashes are consistent between calls
    assert hash == "+aVb5DY1c64pu7wHl8XHvmbClu6Y9fqww8QDOrlrtCM="

    # checks that different arguments yield different hashes
    kwargs2 = copy.deepcopy(kwargs)
    kwargs2["resolution"] = timedelta(minutes=12)

    hash2 = hash_function_arguments(args, kwargs2)

    assert hash != hash2


def test_scheduling_multiple_triggers(
    caplog, db, app, add_charging_station_assets, setup_test_data
):
    caplog.set_level(
        logging.INFO
    )  # setting the logging level of the log capture fixture

    soc_at_start = 1
    target_soc = 5
    duration_until_target = timedelta(hours=2)

    charging_station = Sensor.query.filter(
        Sensor.name == "Test charging station"
    ).one_or_none()
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    target_datetime = start + duration_until_target
    resolution = timedelta(minutes=15)
    soc_targets = [dict(datetime=target_datetime.isoformat(), value=target_soc)]

    assert (
        DataSource.query.filter_by(name="FlexMeasures", type="scheduling script")
        .where()
        .one_or_none()
        is None
    )  # Make sure the scheduler data source isn't there

    # schedule 1 job
    job1 = create_scheduling_job(
        sensor=charging_station,
        start=start,
        end=end,
        belief_time=start,
        resolution=resolution,
        flex_model={"soc-at-start": soc_at_start, "soc-targets": soc_targets},
    )
    work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)

    caplog.clear()

    # Schedule same job
    job2 = create_scheduling_job(
        sensor=charging_station,
        start=start,
        end=end,
        belief_time=start,
        resolution=resolution,
        flex_model={"soc-at-start": soc_at_start, "soc-targets": soc_targets},
    )
    work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)

    # checking that the decorator is detecting that the job is repeated
    assert (
        sum(
            [
                "The function create_scheduling_job has been called alread with the same arguments. Skipping..."
                in rec.message
                for rec in caplog.records
            ]
        )
        == 1
    )

    # checking that they have the same job id
    assert job1.id == job2.id

    # checking that a different schedule trigger is actually computed when a nested field is changed
    soc_at_start = 2
    job3 = create_scheduling_job(
        sensor=charging_station,
        start=start,
        end=end,
        belief_time=start,
        resolution=resolution,
        flex_model={"soc-at-start": soc_at_start, "soc-targets": soc_targets},
    )
    work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)

    assert job3.id != job1.id
