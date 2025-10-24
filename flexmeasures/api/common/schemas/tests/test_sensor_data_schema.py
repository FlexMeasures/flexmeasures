from datetime import timedelta, datetime
import json
import pytest
import pytz

from marshmallow import ValidationError
import pandas as pd
from unittest import mock

from flexmeasures.api.common.schemas.sensor_data import (
    SingleValueField,
    PostSensorDataSchema,
    GetSensorDataSchema,
)
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.forecasting import create_forecasting_jobs
from flexmeasures.data.services.scheduling import create_scheduling_job
from flexmeasures.data.services.sensors import (
    get_stalenesses,
    get_statuses,
    build_asset_jobs_data,
    get_asset_sensors_metadata,
)
from flexmeasures.data.schemas.reporting import StatusSchema
from flexmeasures.utils.time_utils import as_server_time


@pytest.mark.parametrize(
    "deserialization_input, exp_deserialization_output",
    [
        (
            "PT1H",
            timedelta(hours=1),
        ),
        (
            "PT15M",
            timedelta(minutes=15),
        ),
    ],
)
def test_resolution_field_deserialization(
    deserialization_input,
    exp_deserialization_output,
):
    """Check parsing the resolution field of the GetSensorDataSchema schema.

    These particular ISO durations are expected to be parsed as python timedeltas.
    """
    # todo: extend test cases with some nominal durations when timely-beliefs supports these
    #       see https://github.com/SeitaBV/timely-beliefs/issues/13
    vf = GetSensorDataSchema._declared_fields["resolution"]
    deser = vf.deserialize(deserialization_input)
    assert deser == exp_deserialization_output


@pytest.mark.parametrize(
    "deserialization_input, exp_deserialization_output",
    [
        (
            1,
            [1],
        ),
        (
            2.7,
            [2.7],
        ),
        (
            [1],
            [1],
        ),
        (
            [2.7],
            [2.7],
        ),
        (
            [1, None, 3],  # sending a None/null value as part of a list is allowed
            [1, None, 3],
        ),
        (
            [None],  # sending a None/null value as part of a list is allowed
            [None],
        ),
    ],
)
def test_value_field_deserialization(
    deserialization_input,
    exp_deserialization_output,
):
    """Testing straightforward cases"""
    vf = PostSensorDataSchema._declared_fields["values"]
    deser = vf.deserialize(deserialization_input)
    assert deser == exp_deserialization_output


@pytest.mark.parametrize(
    "serialization_input, exp_serialization_output",
    [
        (
            1,
            [1],
        ),
        (
            2.7,
            [2.7],
        ),
    ],
)
def test_value_field_serialization(
    serialization_input,
    exp_serialization_output,
):
    """Testing straightforward cases"""
    vf = SingleValueField()
    ser = vf.serialize("values", {"values": serialization_input})
    assert ser == exp_serialization_output


@pytest.mark.parametrize(
    "deserialization_input, error_msg",
    [
        (
            ["three", 4],
            "Not a valid number",
        ),
        (
            "3, 4",
            "Not a valid number",
        ),
        (
            None,
            "may not be null",  # sending a single None/null value is not allowed
        ),
    ],
)
def test_value_field_invalid(deserialization_input, error_msg):
    sf = SingleValueField()
    with pytest.raises(ValidationError) as ve:
        sf.deserialize(deserialization_input)
    assert error_msg in str(ve)


# knowledge time 2016-01-01T12:00+01
@pytest.mark.parametrize(
    "now, expected_staleness, expected_stale",
    [
        (
            # Knowledge time 12 hours from now
            "2016-01-01T00:00+01",
            None,  # Not known yet
            True,
        ),
        (
            # Knowledge time 12 hours and 18 minutes ago
            "2016-01-02T00:18+01",
            timedelta(hours=12, minutes=18),
            True,
        ),
        (
            # Knowledge time 1 day and 12 hours ago
            "2016-01-03T00:00+01",
            timedelta(days=1, hours=12),
            True,
        ),
        (
            # Knowledge time 1 min ago
            "2016-01-01T12:01+01",
            timedelta(minutes=1),
            False,
        ),
    ],
)
def test_get_status_single_source(
    add_market_prices,
    now,
    expected_staleness,
    expected_stale,
):
    sensor = add_market_prices["epex_da"]
    staleness_search = dict()

    now = pd.Timestamp(now)
    stalenesses = get_stalenesses(
        sensor=sensor, staleness_search=staleness_search, now=now
    )
    if stalenesses is not None:
        stalenesses.pop("forecaster", None)

    source_type_of_interest = "reporter"

    if expected_staleness is None:
        assert stalenesses is None
    else:
        assert stalenesses[source_type_of_interest] == (mock.ANY, expected_staleness)

    status_specs = {
        "staleness_search": staleness_search,
        "max_staleness": "PT1H",
        "max_future_staleness": "-PT12H",
    }
    assert StatusSchema().load(status_specs)

    sensor_statuses = get_statuses(
        sensor=sensor,
        status_specs=status_specs,
        now=now,
    )

    if not expected_staleness:
        return  # the following

    sensor_statuses = [
        status
        for status in sensor_statuses
        if status["source_type"] == source_type_of_interest
    ]
    sensor_status = sensor_statuses[0]

    assert sensor_status["staleness"] == expected_staleness
    assert sensor_status["stale"] == expected_stale
    if stalenesses is None:
        assert sensor_status["source_type"] is None
    else:
        assert sensor_status["source_type"] == source_type_of_interest


# both sources have the same data
# max_staleness for forecaster is 12 hours
# max_staleness for reporter is 1 day
@pytest.mark.parametrize(
    "now, expected_forecaster_staleness, expected_forecaster_stale, expect_forecaster_reason, expected_reporter_staleness, expected_reporter_stale, expect_reporter_reason",
    [
        (
            # Both stale
            # Last event start at 2016-01-02T23:00+01 10 hours from now,
            # with knowledge time 2016-01-01T12:00+01, 1 day 1 hour ago
            "2016-01-02T13:00+01",
            timedelta(hours=10),
            True,
            "most recent data is 10 hours in the future, but should be more than 12 hours in the future",
            timedelta(days=1, hours=1),
            True,
            "most recent data is 1 day and 1 hour old, but should not be more than 1 day old",
        ),
        (
            # Both not stale
            # Last event start at 2016-01-02T23:00+01 13 hours from now,
            # with knowledge time 2016-01-01T12:00+01, 22 hours ago
            "2016-01-02T10:00+01",
            timedelta(hours=13),
            False,
            "most recent data is 13 hours in the future, which is not less than 12 hours in the future",
            timedelta(hours=22),
            False,
            "most recent data is 22 hours old, which is not more than 1 day old",
        ),
        (
            # Reporter not stale, forecaster stale
            # Last event start at 2016-01-02T23:00+01,
            # with knowledge time 2016-01-01T12:00+01, 1 day ago
            "2016-01-02T12:00+01",
            timedelta(hours=11),
            True,
            "most recent data is 11 hours in the future, but should be more than 12 hours in the future",
            timedelta(days=1),
            False,
            "most recent data is 1 day old, which is not more than 1 day old",
        ),
        (
            # Both stale, no data in the future
            # Last event start at 2016-01-02T23:00+01,
            # with knowledge time 2016-01-01T12:00+01, 2 days ago
            "2016-01-03T12:00+01",
            None,
            True,
            "Found no future data which this source should have",
            timedelta(days=2),
            True,
            "most recent data is 2 days old, but should not be more than 1 day old",
        ),
    ],
)
def test_get_status_multi_source(
    add_market_prices,
    now,
    expected_forecaster_staleness,
    expected_forecaster_stale,
    expect_forecaster_reason,
    expected_reporter_staleness,
    expected_reporter_stale,
    expect_reporter_reason,
):
    sensor = add_market_prices["epex_da"]
    now = pd.Timestamp(now)

    sensor_statuses = get_statuses(
        sensor=sensor,
        now=now,
    )
    for sensor_status in sensor_statuses:
        if sensor_status["source_type"] == "reporter":
            assert sensor_status["staleness"] == expected_reporter_staleness
            assert sensor_status["stale"] == expected_reporter_stale
            assert sensor_status["reason"] == expect_reporter_reason
        if sensor_status["source_type"] == "forecaster":
            assert sensor_status["staleness"] == expected_forecaster_staleness
            assert sensor_status["stale"] == expected_forecaster_stale
            assert sensor_status["reason"] == expect_forecaster_reason


@pytest.mark.parametrize(
    "source_type, now, expected_staleness, expected_stale, expected_stale_reason",
    [
        # sensor resolution is 15 min
        (
            "demo script",
            # Last event start (in the past) at 2015-01-02T07:45+01, with knowledge time 2015-01-02T08:00+01, 29 minutes ago
            "2015-01-02T08:29+01",
            timedelta(minutes=29),
            False,
            "not more than 30 minutes old",
        ),
        (
            "demo script",
            # Last event start (in the past) at 2015-01-02T07:45+01, with knowledge time 2015-01-02T08:00+01, 31 minutes ago
            "2015-01-02T08:31+01",
            timedelta(minutes=31),
            True,
            "more than 30 minutes old",
        ),
        (
            "scheduler",
            # Last event start (in the future) at 2016-01-02T07:45+01, in 24 hours 45 minutes
            "2016-01-01T07:00+01",
            timedelta(minutes=24 * 60 + 45),
            False,
            "not less than 12 hours in the future",
        ),
    ],
)
def test_get_status_no_status_specs(
    capacity_sensors,
    source_type,
    now,
    expected_staleness,
    expected_stale,
    expected_stale_reason,
):
    sensor = capacity_sensors["production"]
    now = pd.Timestamp(now)
    sensor_statuses = get_statuses(
        sensor=sensor,
        status_specs=None,
        now=now,
    )

    assert source_type in [ss["source_type"] for ss in sensor_statuses]
    for sensor_status in sensor_statuses:
        if sensor_status["source_type"] == source_type:
            assert sensor_status["staleness"] == expected_staleness
            assert sensor_status["stale"] == expected_stale
            assert expected_stale_reason in sensor_status["reason"]


def test_asset_sensors_metadata(
    db, mock_get_statuses, add_weather_sensors, add_battery_assets
):
    """
    Test the function to build status meta data structure, using a weather station asset.
    We include the sensor of a different asset (a battery) via the flex context
    (as production price, does not make too much sense actually).
    One sensor which the asset already includes is also set in the context as inflexible device,
    so we can test if the relationship tagging works for that as well.
    """
    asset = add_weather_sensors["asset"]
    battery_asset = add_battery_assets["Test battery"]
    wind_sensor, temperature_sensor = (
        add_weather_sensors["wind"],
        add_weather_sensors["temperature"],
    )

    production_price_sensor = Sensor(
        name="production price",
        generic_asset=battery_asset,
        event_resolution=timedelta(minutes=5),
        unit="EUR/MWh",
    )
    db.session.add(production_price_sensor)
    db.session.flush()

    asset.flex_context["production-price"] = {"sensor": production_price_sensor.id}
    asset.flex_context["inflexible-device-sensors"] = [temperature_sensor.id]
    db.session.add(asset)

    wind_speed_res, temperature_res = {"staleness": True}, {"staleness": False}
    production_price_res = {"staleness": True}
    mock_get_statuses.side_effect = (
        [wind_speed_res],
        [temperature_res],
        [production_price_res],
    )

    status_data = get_asset_sensors_metadata(asset=asset)

    assert status_data != [
        {
            "name": "wind speed",
            "id": wind_sensor.id,
            "asset_name": asset.name,
        },
        {
            "name": "temperature",
            "id": temperature_sensor.id,
            "asset_name": asset.name,
        },
        {
            "name": "production price",
            "id": production_price_sensor.id,
            "asset_name": battery_asset.name,
        },
    ]

    # Make sure the Wind speed is not in the sensor data as it is not in sensors_to_show or flex-context
    assert status_data == [
        {
            "name": "temperature",
            "id": temperature_sensor.id,
            "asset_name": asset.name,
        },
        {
            "name": "production price",
            "id": production_price_sensor.id,
            "asset_name": battery_asset.name,
        },
    ]


def custom_model_params():
    """little training as we have little data, turn off transformations until they let this test run (TODO)"""
    return dict(
        training_and_testing_period=timedelta(hours=2),
        outcome_var_transformation=None,
        regressor_transformation={},
    )


def test_build_asset_jobs_data(db, app, add_battery_assets):
    """Check that we get both types of jobs for a battery asset."""
    battery_asset = add_battery_assets["Test battery"]
    battery = battery_asset.sensors[0]
    tz = pytz.timezone("Europe/Amsterdam")
    start, end = tz.localize(datetime(2015, 1, 2)), tz.localize(datetime(2015, 1, 3))

    scheduling_job = create_scheduling_job(
        asset_or_sensor=battery,
        start=start,
        end=end,
        belief_time=start,
        resolution=timedelta(minutes=15),
    )
    forecasting_jobs = create_forecasting_jobs(
        start_of_roll=as_server_time(datetime(2015, 1, 1, 6)),
        end_of_roll=as_server_time(datetime(2015, 1, 1, 7)),
        horizons=[timedelta(hours=1)],
        sensor_id=battery.id,
        custom_model_params=custom_model_params(),
    )

    jobs_data = build_asset_jobs_data(battery_asset)
    assert sorted([j["queue"] for j in jobs_data]) == ["forecasting", "scheduling"]
    for job_data in jobs_data:
        metadata = json.loads(job_data["metadata"])
        if job_data["queue"] == "forecasting":
            assert metadata["job_id"] == forecasting_jobs[0].id
        else:
            assert metadata["job_id"] == scheduling_job.id
        assert job_data["status"] == "queued"
        assert job_data["entity"] == f"sensor: {battery.name} (Id: {battery.id})"

    # Clean up queues
    app.queues["scheduling"].empty()
    app.queues["forecasting"].empty()
    assert app.queues["scheduling"].count == 0
    assert app.queues["forecasting"].count == 0
