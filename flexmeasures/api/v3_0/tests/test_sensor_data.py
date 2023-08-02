from __future__ import annotations

from datetime import timedelta

from flask import url_for
import pytest

from flexmeasures import Sensor, Source, User
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v3_0.tests.utils import make_sensor_data_request_for_gas_sensor


def test_get_no_sensor_data(
    client,
    setup_api_test_data: dict[str, Sensor],
):
    """Check the /sensors/data endpoint for fetching data for a period without any data."""
    sensor = setup_api_test_data["some gas sensor"]
    message = {
        "sensor": f"ea1.2021-01.io.flexmeasures:fm1.{sensor.id}",
        "start": "1921-05-02T00:00:00+02:00",  # we have loaded no test data for this year
        "duration": "PT1H20M",
        "horizon": "PT0H",
        "unit": "m³/h",
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
    # We expect only null values (which are converted to None by .json)
    assert all(a == b for a, b in zip(values, [None, None, None, None]))


def test_get_sensor_data(
    client,
    setup_api_test_data: dict[str, Sensor],
    setup_roles_users: dict[str, User],
):
    """Check the /sensors/data endpoint for fetching 1 hour of data of a 10-minute resolution sensor."""
    sensor = setup_api_test_data["some gas sensor"]
    source: Source = User.query.get(
        setup_roles_users["Test Supplier User"]
    ).data_source[0]
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
    setup_api_test_data: dict[str, Sensor],
    setup_roles_users: dict[str, User],
):
    """Check the /sensors/data endpoint for fetching 1 hour of data of an instantaneous sensor."""
    sensor = setup_api_test_data["some temperature sensor"]
    source: Source = User.query.get(
        setup_roles_users["Test Supplier User"]
    ).data_source[0]
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


@pytest.mark.parametrize("use_auth", [False, True])
def test_post_sensor_data_bad_auth(client, setup_api_test_data, use_auth):
    """
    Attempt to post sensor data with insufficient or missing auth.
    """
    # the case without auth: authentication will fail
    headers = {"content-type": "application/json"}
    if use_auth:
        # in this case, we successfully authenticate,
        # but fail authorization (not member of the account in which the sensor lies)
        headers["Authorization"] = get_auth_token(
            client, "test_dummy_user_3@seita.nl", "testtest"
        )

    post_data = make_sensor_data_request_for_gas_sensor()
    post_data_response = client.post(
        url_for("SensorAPI:post_data"),
        headers=headers,
        json=post_data,
    )
    print("Server responded with:\n%s" % post_data_response.data)
    if use_auth:
        assert post_data_response.status_code == 403
    else:
        assert post_data_response.status_code == 401


@pytest.mark.parametrize(
    "request_field, new_value, error_field, error_text",
    [
        ("start", "2021-06-07T00:00:00", "start", "Not a valid aware datetime"),
        (
            "duration",
            "PT30M",
            "_schema",
            "Resolution of 0:05:00 is incompatible",
        ),  # downsampling not supported
        ("sensor", "ea1.2021-01.io.flexmeasures:fm1.666", "sensor", "doesn't exist"),
        ("unit", "m", "_schema", "Required unit"),
        ("type", "GetSensorDataRequest", "type", "Must be one of"),
    ],
)
def test_post_invalid_sensor_data(
    client, setup_api_test_data, request_field, new_value, error_field, error_text
):
    post_data = make_sensor_data_request_for_gas_sensor()
    post_data[request_field] = new_value
    # this guy is allowed to post sensorData
    auth_token = get_auth_token(client, "test_supplier_user_4@seita.nl", "testtest")
    response = client.post(
        url_for("SensorAPI:post_data"),
        json=post_data,
        headers={"Authorization": auth_token},
    )
    print(response.json)
    assert response.status_code == 422
    assert error_text in response.json["message"]["json"][error_field][0]


def test_post_sensor_data_twice(client, setup_api_test_data):
    auth_token = get_auth_token(client, "test_supplier_user_4@seita.nl", "testtest")
    post_data = make_sensor_data_request_for_gas_sensor()

    # Check that 1st time posting the data succeeds
    response = client.post(
        url_for("SensorAPI:post_data"),
        json=post_data,
        headers={"Authorization": auth_token},
    )
    print(response.json)
    assert response.status_code == 200

    # Check that 2nd time posting the same data succeeds informatively
    response = client.post(
        url_for("SensorAPI:post_data"),
        json=post_data,
        headers={"Authorization": auth_token},
    )
    print(response.json)
    assert response.status_code == 200
    assert "data has already been received" in response.json["message"]

    # Check that replacing data fails informatively
    post_data["values"][0] = 100
    response = client.post(
        url_for("SensorAPI:post_data"),
        json=post_data,
        headers={"Authorization": auth_token},
    )
    print(response.json)
    assert response.status_code == 403
    assert "data represents a replacement" in response.json["message"]
