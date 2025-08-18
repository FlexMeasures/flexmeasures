from __future__ import annotations

from datetime import timedelta
from flask import url_for
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from flexmeasures import Sensor, Source, User
from flexmeasures.api.v3_0.tests.utils import make_sensor_data_request_for_gas_sensor


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_get_no_sensor_data(
    client,
    setup_api_test_data: dict[str, Sensor],
    requesting_user,
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
    response = client.get(
        url_for("SensorAPI:get_data"),
        query_string=message,
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    values = response.json["values"]
    # We expect only null values (which are converted to None by .json)
    assert all(a == b for a, b in zip(values, [None, None, None, None]))


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_get_sensor_data(
    client,
    setup_api_test_data: dict[str, Sensor],
    setup_roles_users: dict[str, User],
    requesting_user,
    db,
):
    """Check the /sensors/data endpoint for fetching 1 hour of data of a 10-minute resolution sensor."""
    sensor = setup_api_test_data["some gas sensor"]
    source: Source = db.session.get(
        User, setup_roles_users["Test Supplier User"]
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
    response = client.get(
        url_for("SensorAPI:get_data"),
        query_string=message,
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    values = response.json["values"]
    # We expect two data points (from conftest) followed by 2 null values (which are converted to None by .json)
    # The first data point averages [91.3, 91.7], and the second data point averages [92.1, None].
    assert all(a == b for a, b in zip(values, [91.5, 92.1, None, None]))


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_get_instantaneous_sensor_data(
    client,
    setup_api_test_data: dict[str, Sensor],
    setup_roles_users: dict[str, User],
    requesting_user,
    db,
):
    """Check the /sensors/data endpoint for fetching 1 hour of data of an instantaneous sensor."""
    sensor = setup_api_test_data["some temperature sensor"]
    source: Source = db.session.get(
        User, setup_roles_users["Test Supplier User"]
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
    response = client.get(
        url_for("SensorAPI:get_data"),
        query_string=message,
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    values = response.json["values"]
    # We expect two data point (from conftest) followed by 2 null values (which are converted to None by .json)
    # The first data point is the first of [815, 817], and the second data point is the first of [818, None].
    assert all(a == b for a, b in zip(values, [815, 818, None, None]))


@pytest.mark.parametrize(
    "requesting_user, status_code",
    [
        (None, 401),  # the case without auth: authentication will fail
        (
            "test_dummy_user_3@seita.nl",
            403,
        ),  # in this case, we successfully authenticate, but fail authorization (not member of the account in which the sensor lies)
    ],
    indirect=["requesting_user"],
)
def test_post_sensor_data_bad_auth(
    client, setup_api_test_data, requesting_user, status_code
):
    """
    Attempt to post sensor data with insufficient or missing auth.
    """
    post_data = make_sensor_data_request_for_gas_sensor()
    post_data_response = client.post(
        url_for("SensorAPI:post_data"),
        json=post_data,
    )
    print("Server responded with:\n%s" % post_data_response.data)
    assert post_data_response.status_code == status_code


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
@pytest.mark.parametrize(
    "requesting_user",
    [
        "test_supplier_user_4@seita.nl",  # this guy is allowed to post sensorData
    ],
    indirect=True,
)
def test_post_invalid_sensor_data(
    client,
    setup_api_test_data,
    request_field,
    new_value,
    error_field,
    error_text,
    requesting_user,
):
    post_data = make_sensor_data_request_for_gas_sensor()
    post_data[request_field] = new_value

    response = client.post(
        url_for("SensorAPI:post_data"),
        json=post_data,
    )
    print(response.json)
    assert response.status_code == 422
    assert error_text in response.json["message"]["json"][error_field][0]


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_post_sensor_data_twice(client, setup_api_test_data, requesting_user, db):
    post_data = make_sensor_data_request_for_gas_sensor()

    @event.listens_for(Engine, "handle_error")
    def receive_handle_error(exception_context):
        """
        Check that the error that we are getting is of type IntegrityError.
        """
        error_info = exception_context.sqlalchemy_exception

        # If the assert failed, we would get a 500 status code
        assert error_info.__class__.__name__ == "IntegrityError"

    # Check that 1st time posting the data succeeds
    response = client.post(
        url_for("SensorAPI:post_data"),
        json=post_data,
    )
    print(response.json)
    assert response.status_code == 200

    # Check that 2nd time posting the same data succeeds informatively
    response = client.post(
        url_for("SensorAPI:post_data"),
        json=post_data,
    )
    print(response.json)
    assert response.status_code == 200
    assert "data has already been received" in response.json["message"]

    # Check that replacing data fails informatively
    post_data["values"][0] = 100
    response = client.post(
        url_for("SensorAPI:post_data"),
        json=post_data,
    )
    print(response.json)
    assert response.status_code == 403
    assert "data represents a replacement" in response.json["message"]

    # at this point, the transaction has failed and needs to be rolled back.
    db.session.rollback()


@pytest.mark.parametrize(
    "num_values, status_code, message, saved_rows",
    [
        (1, 200, "Request has been processed.", 1),
        (
            2,
            422,
            "Cannot save multiple instantaneous values that overlap. That is, two values spanning the same moment (a zero duration). Try sending a single value or definining a non-zero duration.",
            0,
        ),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_post_sensor_instantaneous_data(
    client,
    setup_api_test_data,
    num_values,
    status_code,
    message,
    saved_rows,
    requesting_user,
):
    post_data = make_sensor_data_request_for_gas_sensor(
        sensor_name="empty temperature sensor",
        num_values=num_values,
        unit="°C",
        duration="PT0H",
    )
    sensor = setup_api_test_data["empty temperature sensor"]
    rows = len(sensor.search_beliefs())

    # Check that 1st time posting the data succeeds
    response = client.post(
        url_for("SensorAPI:post_data"),
        json=post_data,
    )

    assert response.status_code == status_code
    if status_code == 422:
        assert response.json["message"]["json"]["_schema"][0] == message
    else:
        assert response.json["message"] == message

    assert len(sensor.search_beliefs()) - rows == saved_rows
