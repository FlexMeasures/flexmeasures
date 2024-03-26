from datetime import timedelta
import pytest

from marshmallow import ValidationError
import pandas as pd

from flexmeasures.api.common.schemas.sensor_data import (
    SingleValueField,
    PostSensorDataSchema,
    GetSensorDataSchema,
)
from flexmeasures.data.services.sensors import (
    get_stalenesses,
    get_statuses,
    build_sensor_status_data,
)
from flexmeasures.data.schemas.reporting import StatusSchema


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
            # Last event start at 2015-01-02T07:45+01, with knowledge time 2015-01-02T08:00+01, 40 minutes from now
            "2015-01-02T07:20+01",
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
            # Last event start of Seita's belief at 2015-01-02T07:45+01, with knowledge time 2015-01-02T08:00+01, 2 minutes from now
            "2015-01-02T07:58+01",
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
    ],
)
def test_get_status_single_source(
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
            if source.name == source_name:
                deserialized_staleness_search = dict(source=source)
                serialized_staleness_search = {"source": source.id}

    now = pd.Timestamp(now)
    stalenesses = get_stalenesses(
        sensor=sensor, staleness_search=deserialized_staleness_search, now=now
    )
    if stalenesses is not None:
        stalenesses.pop("forecaster", None)

    source_name = source_name if source_name else "Seita"
    if expected_staleness is None:
        assert stalenesses is None
    else:
        assert stalenesses == {source_name: expected_staleness}

    status_specs = {
        "staleness_search": serialized_staleness_search,
        "max_staleness": "PT1H",
        "max_future_staleness": "-PT12H",
    }
    assert StatusSchema().load(status_specs)

    sensor_statuses = get_statuses(
        sensor=sensor,
        status_specs=status_specs,
        now=now,
    )
    sensor_statuses = [
        status for status in sensor_statuses if status["source"] != "forecaster"
    ]
    assert len(sensor_statuses) == 1

    sensor_status = sensor_statuses[0]
    assert sensor_status["staleness"] == expected_staleness
    assert sensor_status["stale"] == expected_stale
    if stalenesses is None:
        assert sensor_status["source"] is None
    else:
        assert sensor_status["source"] == source_name


# both sources have the same data
# max_staleness for forecaster is 12 hours
# max_staleness for Seita is 1 day
@pytest.mark.parametrize(
    "now, expected_forecaster_staleness, expected_forecaster_stale, expect_forecaster_reason, expected_seita_staleness, expected_seita_stale, expect_seita_reason",
    [
        (
            # Both stale
            # Last event start at 2016-01-02T23:00+01 10 hours from now,
            # with knowledge time 2016-01-01T12:00+01, 1 day 1 hour ago
            "2016-01-02T13:00+01",
            timedelta(hours=10),
            True,
            "less than 12 hours in the future",
            timedelta(days=1, hours=1),
            True,
            "more than a day old",
        ),
        (
            # Both not stale
            # Last event start at 2016-01-02T23:00+01 13 hours from now,
            # with knowledge time 2016-01-01T12:00+01, 22 hours ago
            "2016-01-02T10:00+01",
            timedelta(hours=13),
            False,
            "not less than 12 hours in the future",
            timedelta(hours=22),
            False,
            "not more than a day old",
        ),
        (
            # Seita not stale, forecaster stale
            # Last event start at 2016-01-02T23:00+01,
            # with knowledge time 2016-01-01T12:00+01, 1 day ago
            "2016-01-02T12:00+01",
            timedelta(hours=11),
            True,
            "less than 12 hours in the future",
            timedelta(days=1),
            False,
            "not more than a day old",
        ),
    ],
)
def test_get_status_multi_source(
    add_market_prices,
    now,
    expected_forecaster_staleness,
    expected_forecaster_stale,
    expect_forecaster_reason,
    expected_seita_staleness,
    expected_seita_stale,
    expect_seita_reason,
):
    sensor = add_market_prices["epex_da"]
    now = pd.Timestamp(now)

    sensor_statuses = get_statuses(
        sensor=sensor,
        now=now,
    )
    assert len(sensor_statuses) == 2
    for sensor_status in sensor_statuses:
        if sensor_status["source"] == "Seita":
            assert sensor_status["staleness"] == expected_seita_staleness
            assert sensor_status["stale"] == expected_seita_stale
            assert sensor_status["reason"] == expect_seita_reason
        else:
            assert sensor_status["staleness"] == expected_forecaster_staleness
            assert sensor_status["stale"] == expected_forecaster_stale
            assert sensor_status["reason"] == expect_forecaster_reason


def test_build_asset_status_data(mock_get_statuses, add_weather_sensors):
    asset = add_weather_sensors["asset"]

    wind_speed_res, temperature_res = [{"staleness": True}], [{"staleness": False}]
    mock_get_statuses.side_effect = (wind_speed_res, temperature_res)

    status_data = build_sensor_status_data(asset=asset)
    assert status_data == [
        {
            **wind_speed_res[0],
            "name": "wind speed",
            "id": None,
            "asset_name": asset.name,
        },
        {
            **temperature_res[0],
            "name": "temperature",
            "id": None,
            "asset_name": asset.name,
        },
    ]
