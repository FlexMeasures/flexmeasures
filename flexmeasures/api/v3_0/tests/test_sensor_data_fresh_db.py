from __future__ import annotations

from datetime import timedelta

import pytest
from flask import url_for
from timely_beliefs.tests.utils import equal_lists

from flexmeasures import Sensor, Source, User
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v3_0.tests.utils import make_sensor_data_request_for_gas_sensor
from flexmeasures.data.models.time_series import TimedBelief


@pytest.mark.parametrize(
    "num_values, expected_num_values, unit, include_a_null, expected_value",
    [
        (6, 6, "m³/h", False, -11.28),
        (6, 5, "m³/h", True, -11.28),  # NaN value does not enter database
        (6, 6, "m³", False, 6 * -11.28),  # 6 * 10-min intervals per hour
        (6, 6, "l/h", False, -11.28 / 1000),  # 1 m³ = 1000 l
        (3, 6, "m³/h", False, -11.28),  # upsample from 20-min intervals
        (
            1,
            6,
            "m³/h",
            False,
            -11.28,
        ),  # upsample from single value for 1-hour interval, sent as float rather than list of floats
    ],
)
def test_post_sensor_data(
    client,
    setup_api_fresh_test_data,
    num_values,
    expected_num_values,
    unit,
    include_a_null,
    expected_value,
):
    post_data = make_sensor_data_request_for_gas_sensor(
        num_values=num_values, unit=unit, include_a_null=include_a_null
    )
    sensor = Sensor.query.filter(Sensor.name == "some gas sensor").one_or_none()
    filters = (
        TimedBelief.sensor_id == sensor.id,
        TimedBelief.event_start >= post_data["start"],
    )
    beliefs_before = TimedBelief.query.filter(*filters).all()
    print(f"BELIEFS BEFORE: {beliefs_before}")
    assert len(beliefs_before) == 0

    auth_token = get_auth_token(client, "test_supplier_user_4@seita.nl", "testtest")
    response = client.post(
        url_for("SensorAPI:post_data"),
        json=post_data,
        headers={"Authorization": auth_token},
    )
    print(response.json)
    assert response.status_code == 200
    beliefs = TimedBelief.query.filter(*filters).all()
    print(f"BELIEFS AFTER: {beliefs}")
    assert len(beliefs) == expected_num_values
    # check that values are scaled to the sensor unit correctly
    assert equal_lists(
        [b.event_value for b in beliefs], [expected_value] * expected_num_values
    )


def test_get_sensor_data(
    client,
    setup_api_fresh_test_data: dict[str, Sensor],
    setup_roles_users_fresh_db: dict[str, User],
):
    """Check the /sensors/data endpoint for fetching 1 hour of data of a 10-minute resolution sensor."""
    sensor = setup_api_fresh_test_data["some gas sensor"]
    source: Source = setup_roles_users_fresh_db["Test Supplier User"].data_source[0]
    assert sensor.event_resolution == timedelta(minutes=10)
    message = {
        "sensor": f"ea1.2021-01.io.flexmeasures:fm1.{sensor.id}",
        "start": "2021-05-02T00:00:00+02:00",
        "duration": "PT1H20M",
        "horizon": "PT0H",
        "unit": "m³/h",
        "source": source.id,
        "resolution": "PT20M",
    }
    auth_token = get_auth_token(client, "test_supplier_user_4@seita.nl", "testtest")
    response = client.get(
        url_for("SensorAPI:get_data"),
        query_string=message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    values = response.json["values"]
    # We expect two data points (from conftest) followed by 2 null values (which are converted to None by .json)
    # The first data point averages [91.3, 91.7], and the second data point averages [92.1, None].
    assert all(a == b for a, b in zip(values, [91.5, 92.1, None, None]))


def test_get_instantaneous_sensor_data(
    client,
    setup_api_fresh_test_data: dict[str, Sensor],
    setup_roles_users_fresh_db: dict[str, User],
):
    """Check the /sensors/data endpoint for fetching 1 hour of data of an instantaneous sensor."""
    sensor = setup_api_fresh_test_data["some temperature sensor"]
    source: Source = setup_roles_users_fresh_db["Test Supplier User"].data_source[0]
    assert sensor.event_resolution == timedelta(minutes=0)
    message = {
        "sensor": f"ea1.2021-01.io.flexmeasures:fm1.{sensor.id}",
        "start": "2021-05-02T00:00:00+02:00",
        "duration": "PT1H20M",
        "horizon": "PT0H",
        "unit": "°C",
        "source": source.id,
        "resolution": "PT20M",
    }
    auth_token = get_auth_token(client, "test_supplier_user_4@seita.nl", "testtest")
    response = client.get(
        url_for("SensorAPI:get_data"),
        query_string=message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    values = response.json["values"]
    # We expect two data point (from conftest) followed by 2 null values (which are converted to None by .json)
    # The first data point is the first of [815, 817], and the second data point is the first of [818, None].
    assert all(a == b for a, b in zip(values, [815, 818, None, None]))
