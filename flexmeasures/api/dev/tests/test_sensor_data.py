from flask import url_for
import pytest

from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.dev.tests.utils import make_sensor_data_request_for_gas_sensor


@pytest.mark.parametrize("use_auth", [False, True])
def test_post_sensor_data_bad_auth(client, setup_api_test_data, use_auth):
    """
    Attempt to post sensor data with insufficient or missing auth.
    """
    # the case without auth: authentication will fail
    headers = {"content-type": "application/json"}
    if use_auth:
        # in this case, we successfully authenticate,
        # but fail authorization (no admin or MDC role)
        headers["Authorization"] = get_auth_token(
            client, "test_dummy_user_3@seita.nl", "testtest"
        )

    post_data_response = client.post(
        url_for("post_sensor_data"),
        headers=headers,
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
    auth_token = get_auth_token(client, "test_prosumer_user@seita.nl", "testtest")
    response = client.post(
        url_for("post_sensor_data"),
        json=post_data,
        headers={"Authorization": auth_token},
    )
    print(response.json)
    assert response.status_code == 422
    assert error_text in response.json["message"]["json"][error_field][0]


def test_post_sensor_data_twice(client, setup_api_test_data):
    auth_token = get_auth_token(client, "test_prosumer_user@seita.nl", "testtest")
    post_data = make_sensor_data_request_for_gas_sensor()

    # Check that 1st time posting the data succeeds
    response = client.post(
        url_for("post_sensor_data"),
        json=post_data,
        headers={"Authorization": auth_token},
    )
    assert response.status_code == 200

    # Check that 2nd time posting the same data succeeds informatively
    response = client.post(
        url_for("post_sensor_data"),
        json=post_data,
        headers={"Authorization": auth_token},
    )
    print(response.json)
    assert response.status_code == 200
    assert "data has already been received" in response.json["message"]

    # Check that replacing data fails informatively
    post_data["values"][0] = 100
    response = client.post(
        url_for("post_sensor_data"),
        json=post_data,
        headers={"Authorization": auth_token},
    )
    print(response.json)
    assert response.status_code == 403
    assert "data represents a replacement" in response.json["message"]
