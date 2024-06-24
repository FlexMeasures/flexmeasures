from datetime import timedelta, datetime
import json
import pytest
import pytz

from marshmallow import ValidationError
import pandas as pd

from flexmeasures.api.common.schemas.sensor_data import (
    SingleValueField,
    PostSensorDataSchema,
    GetSensorDataSchema,
)
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.forecasting import create_forecasting_jobs
from flexmeasures.data.services.scheduling import create_scheduling_job
from flexmeasures.data.services.sensors import (
    get_staleness,
    get_status,
    build_sensor_status_data,
    build_asset_jobs_data,
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


@pytest.mark.parametrize(
    "now, sensor_type, source_name, expected_staleness, expected_stale",
    [
        (
            # Last event start at 2016-01-01T23:00+01, with knowledge time 2016-01-01T12:00+01, 12 hours from now
            "2016-01-01T00:00+01",
            "market",
            None,
            None,  # Not known yet
            True,
        ),
        (
            # Last event start at 2016-01-01T23:00+01, with knowledge time 2016-01-01T12:00+01, 12 hours and 18 minutes ago
            "2016-01-02T00:18+01",
            "market",
            None,
            timedelta(hours=12, minutes=18),
            True,
        ),
        (
            # Last event start at 2016-01-01T23:00+01, with knowledge time 2016-01-01T12:00+01, 1 day and 12 hours ago
            "2016-01-03T00:00+01",
            "market",
            None,
            timedelta(days=1, hours=12),
            True,
        ),
        (
            # Last event start at 2015-01-01T23:00:00+00:00, with knowledge time 2015-01-01T23:15:00+00:00, 40 minutes from now
            "2015-01-01T22:35+01",
            "production",
            "Seita",
            None,  # Not known yet
            True,
        ),
        (
            # Last event start at 2015-01-02T07:45+01, with knowledge time 2015-01-02T08:00+01, 40 minutes ago (but still less than max PT1H allowed)
            "2015-01-02T08:40+01",
            "production",
            "Seita",
            timedelta(minutes=40),
            False,
        ),
        (
            # Last event start of Seita's belief at 2015-01-01T23:00:00+00:00, with knowledge time 2015-01-01T23:15:00+00:00, 2 minutes from now
            "2015-01-01T23:13+01",
            "production",
            "Seita",
            None,  # Not known yet
            True,
        ),
        (
            # Last event start of Seita's belief at 2015-01-02T07:45+01, with knowledge time 2015-01-02T08:00+01, 4 hours and 42 minutes ago
            "2015-01-02T12:42+01",
            "production",
            "Seita",
            timedelta(hours=4, minutes=42),
            True,
        ),
        (
            # Last event start of DummyScheduler's belief at 2016-01-02T07:45+01, with knowledge time 2016-01-02T08:00+01, 13 hours ago
            "2016-01-02T21:00+01",
            "production",
            "DummySchedule",
            timedelta(hours=13),
            True,
        ),
        (
            # Last event start at 2016-01-02T07:45+01, with knowledge time 2016-01-02T08:00+01, 13 hours ago
            "2016-01-02T21:00+01",
            "production",
            None,
            timedelta(hours=13),
            True,
        ),
    ],
)
def test_get_status(
    add_market_prices,
    capacity_sensors,
    now,
    sensor_type,
    source_name,
    expected_staleness,
    expected_stale,
):
    if sensor_type == "market":
        sensor = add_market_prices["epex_da"]
        deserialized_staleness_search = dict()
        serialized_staleness_search = {}
    elif sensor_type == "production":
        sensor = capacity_sensors["production"]
        deserialized_staleness_search = dict()
        serialized_staleness_search = {}
        for source in sensor.data_sources:
            print(source.name)
            if source.name == source_name:
                deserialized_staleness_search = dict(source=source)
                serialized_staleness_search = {"source": source.id}

    print(deserialized_staleness_search)
    now = pd.Timestamp(now)
    staleness = get_staleness(
        sensor=sensor, staleness_search=deserialized_staleness_search, now=now
    )
    status_specs = {
        "staleness_search": serialized_staleness_search,
        "max_staleness": "PT1H",
    }
    sensor_status = get_status(
        sensor=sensor,
        status_specs=status_specs,
        now=now,
    )

    assert StatusSchema().load(status_specs)
    assert staleness == expected_staleness
    assert sensor_status["staleness"] == expected_staleness
    assert sensor_status["stale"] == expected_stale


@pytest.mark.parametrize(
    "now, expected_staleness, expected_stale, expected_stale_reason",
    [
        # sensor resolution is 15 min
        (
            # Last event start at 2016-01-02T07:45+01, with knowledge time 2016-01-02T08:00+01, 29 minutes ago
            "2016-01-02T08:29+01",
            timedelta(minutes=29),
            False,
            "not more than 30 minutes old",
        ),
        (
            # Last event start at 2016-01-02T07:45+01, with knowledge time 2016-01-02T08:00+01, 31 minutes ago
            "2016-01-02T08:31+01",
            timedelta(minutes=31),
            True,
            "more than 30 minutes old",
        ),
    ],
)
def test_get_status_no_status_specs(
    capacity_sensors,
    now,
    expected_staleness,
    expected_stale,
    expected_stale_reason,
):
    sensor = capacity_sensors["production"]
    now = pd.Timestamp(now)
    sensor_status = get_status(
        sensor=sensor,
        status_specs=None,
        now=now,
    )

    assert sensor_status["staleness"] == expected_staleness
    assert sensor_status["stale"] == expected_stale
    assert sensor_status["reason"] == expected_stale_reason


def test_build_asset_status_data(
    db, mock_get_status, add_weather_sensors, add_battery_assets
):
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

    asset.consumption_price_sensor_id = wind_sensor.id
    asset.production_price_sensor_id = production_price_sensor.id
    asset.inflexible_device_sensors = [temperature_sensor]
    db.session.add(asset)

    wind_speed_res, temperature_res = {"staleness": True}, {"staleness": False}
    production_price_res = {"staleness": True}
    mock_get_status.side_effect = (
        wind_speed_res,
        temperature_res,
        production_price_res,
    )

    status_data = build_sensor_status_data(asset=asset)
    assert status_data == [
        {
            **wind_speed_res,
            "name": "wind speed",
            "id": wind_sensor.id,
            "asset_name": asset.name,
            "relation": "included device;consumption price",
        },
        {
            **temperature_res,
            "name": "temperature",
            "id": temperature_sensor.id,
            "asset_name": asset.name,
            "relation": "included device;inflexible device",
        },
        {
            **production_price_res,
            "name": "production price",
            "id": production_price_sensor.id,
            "asset_name": battery_asset.name,
            "relation": "production price",
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
    # """Test we get both types of jobs for a battery asset."""
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
