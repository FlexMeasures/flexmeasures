from datetime import timedelta, datetime, timezone
import pytest

from marshmallow import ValidationError
import pandas as pd

from flexmeasures.api.common.schemas.sensor_data import (
    SingleValueField,
    PostSensorDataSchema,
    GetSensorDataSchema,
)
from flexmeasures.data.services.sensors import get_staleness, get_status
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
            "2016-01-01T00:00+00",
            "market",
            None,
            timedelta(hours=-11),
            False,
        ),
        (
            "2016-01-02T00:18+00",
            "market",
            None,
            timedelta(hours=13, minutes=18),
            True,
        ),
        (
            "2016-01-03T00:00+00",
            "market",
            None,
            timedelta(days=1, hours=13),
            True,
        ),
        (
            "2016-01-04T00:00+00",
            "market",
            None,
            timedelta(days=2, hours=13),
            True,
        ),
        (
            "2016-01-02T05:00+00",
            "market",
            None,
            timedelta(hours=18),
            True,
        ),
        (
            "2016-01-02T13:00+00",
            "market",
            None,
            timedelta(days=1, hours=2),
            True,
        ),
        (
            "2016-01-02T21:00+00",
            "market",
            None,
            timedelta(days=1, hours=10),
            True,
        ),
        (
            "2015-01-02T06:20+00",
            "production",
            "Seita",
            timedelta(minutes=-40),
            True,
        ),
        (
            "2015-01-02T03:18+00",
            "production",
            "Seita",
            timedelta(hours=-3, minutes=-42),
            False,
        ),
        (
            "2016-01-02T21:00+00",
            "production",
            "DummySchedule",
            timedelta(hours=14),
            True,
        ),
        (
            "2016-01-02T21:00+00",
            "production",
            None,
            timedelta(hours=14),
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
        staleness_search = {}
    elif sensor_type == "production":
        sensor = capacity_sensors["production"]
        staleness_search = {}
        for source in sensor.data_sources:
            print(source.name)
            if source.name == source_name:
                source_id = source.id
                staleness_search = {"source": source_id}

    print(staleness_search)
    now = pd.Timestamp(now)
    staleness = get_staleness(sensor=sensor, staleness_search=staleness_search, now=now)
    status_specs = {"staleness_search": staleness_search, "max_staleness": "PT1H"}
    sensor_status = get_status(
        sensor=sensor,
        status_specs=status_specs,
        now=now,
    )

    assert StatusSchema().load(status_specs)
    assert staleness == expected_staleness
    assert sensor_status["staleness"] == expected_staleness
    assert sensor_status["stale"] == expected_stale
