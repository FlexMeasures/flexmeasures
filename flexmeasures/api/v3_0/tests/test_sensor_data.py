from __future__ import annotations

from datetime import timedelta
from flask import url_for
import pandas as pd
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from flexmeasures import Sensor, Source, User
from flexmeasures.api.v3_0.tests.conftest import GAS_MEASUREMENTS_10MIN
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
        "start": "1921-05-02T00:00:00+02:00",  # we have loaded no test data for this year
        "duration": "PT1H20M",
        "horizon": "PT0H",
        "unit": "m³/h",
        "resolution": "PT20M",
    }
    response = client.get(
        url_for("SensorAPI:get_data", id=sensor.id),
        query_string=message,
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    values = response.json["values"]
    # We expect only null values (which are converted to None by .json)
    assert all(a == b for a, b in zip(values, [None, None, None, None]))


@pytest.mark.parametrize("use_oldstyle_endpoint", [True, False])
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_get_sensor_data(
    client,
    setup_api_test_data: dict[str, Sensor],
    setup_roles_users: dict[str, User],
    use_oldstyle_endpoint,
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
        "start": "2021-05-02T00:00:00+02:00",
        "duration": "PT1H20M",
        "horizon": "PT0H",
        "unit": "m³/h",
        "source": source.id,
        "resolution": "PT20M",
    }
    if use_oldstyle_endpoint:  # remove this when we remove those endpoints one day
        message["sensor"] = f"ea1.2021-01.io.flexmeasures:fm1.{sensor.id}"
        url = url_for("SensorEntityAddressAPI:get_data_deprecated")
    else:
        url = url_for("SensorAPI:get_data", id=sensor.id)
    response = client.get(url, query_string=message)
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    values = response.json["values"]
    # GAS_MEASUREMENTS_10MIN stores 10-minute values; resampled to 20-minute resolution:
    #   - 1st interval: average of [91.3, 91.7] = 91.5
    #   - 2nd interval: average of [92.1, None] = 92.1 (only one value present)
    #   - 3rd and 4th intervals: no data → None
    expected = [
        sum(GAS_MEASUREMENTS_10MIN[0:2]) / 2,  # 91.5
        GAS_MEASUREMENTS_10MIN[2],  # 92.1
        None,
        None,
    ]
    assert values == expected


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
        "start": "2021-05-02T00:00:00+02:00",
        "duration": "PT1H20M",
        "horizon": "PT0H",
        "unit": "°C",
        "source": source.id,
        "resolution": "PT20M",
    }
    response = client.get(
        url_for("SensorAPI:get_data", id=sensor.id),
        query_string=message,
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    values = response.json["values"]
    # We expect two data point (from conftest) followed by 2 null values (which are converted to None by .json)
    # The first data point is the first of [815, 817], and the second data point is the first of [818, None].
    assert all(a == b for a, b in zip(values, [815, 818, None, None]))


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_get_sensor_data_filtered_by_source_account(
    client,
    setup_api_test_data: dict[str, Sensor],
    setup_roles_users: dict[str, User],
    requesting_user,
    db,
):
    """Check that GET /sensors/<id>/data can filter by the account linked to a source."""
    sensor = setup_api_test_data["some gas sensor"]
    source_user = db.session.get(User, setup_roles_users["Test Supplier User"])
    assert source_user.account_id is not None
    message = {
        "start": "2021-05-02T00:00:00+02:00",
        "duration": "PT1H20M",
        "horizon": "PT0H",
        "unit": "m³/h",
        "source-account": source_user.account_id,
        "resolution": "PT20M",
    }
    response = client.get(
        url_for("SensorAPI:get_data", id=sensor.id),
        query_string=message,
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    values = response.json["values"]
    # The fixture also stores data from an accountless "Other source".
    # Filtering by the user account should exclude those points.
    # GAS_MEASUREMENTS_10MIN stores 10-minute values; resampled to 20-minute resolution:
    #   - 1st interval: average of [91.3, 91.7] = 91.5
    #   - 2nd interval: average of [92.1, None] = 92.1 (only one value present)
    expected = [
        sum(GAS_MEASUREMENTS_10MIN[0:2]) / 2,  # 91.5
        GAS_MEASUREMENTS_10MIN[2],  # 92.1
        None,
        None,
    ]
    assert all(a == b for a, b in zip(values, expected))


@pytest.mark.parametrize(
    "source_type, expected_statuscode, expected_values",
    [
        (
            "user",
            200,
            [
                sum(GAS_MEASUREMENTS_10MIN[0:2]) / 2,  # 91.5
                GAS_MEASUREMENTS_10MIN[2],  # 92.1
                None,
                None,
            ],
        ),
        (
            "demo script",
            200,
            [
                GAS_MEASUREMENTS_10MIN[0],  # 91.3
                GAS_MEASUREMENTS_10MIN[2],  # 92.1
                None,
                None,
            ],
        ),
        ("scheduler", 422, [None, None, None, None]),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_get_sensor_data_filtered_by_source_type(
    client,
    setup_api_test_data: dict[str, Sensor],
    requesting_user,
    source_type,
    expected_statuscode,
    expected_values,
):
    """Check that GET /sensors/<id>/data can filter by source type."""
    sensor = setup_api_test_data["some gas sensor"]
    message = {
        "start": "2021-05-02T00:00:00+02:00",
        "duration": "PT1H20M",
        "horizon": "PT0H",
        "unit": "m³/h",
        "source-type": source_type,
        "resolution": "PT20M",
    }
    response = client.get(
        url_for("SensorAPI:get_data", id=sensor.id),
        query_string=message,
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == expected_statuscode
    if expected_statuscode == 200:
        assert response.json["values"] == expected_values
    else:
        assert (
            f"No data source with source-type '{source_type}' has recorded any data on this sensor."
            in response.json["message"]["combined_sensor_data_description"][
                "source-type"
            ]
        )


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_get_sensor_data_rejects_empty_source_type(
    client,
    setup_api_test_data: dict[str, Sensor],
    requesting_user,
):
    """Check that GET /sensors/<id>/data rejects an empty source-type filter."""
    sensor = setup_api_test_data["some gas sensor"]
    message = {
        "start": "2021-05-02T00:00:00+02:00",
        "duration": "PT1H20M",
        "horizon": "PT0H",
        "unit": "m³/h",
        "source-type": "",
        "resolution": "PT20M",
    }
    response = client.get(
        url_for("SensorAPI:get_data", id=sensor.id),
        query_string=message,
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 422
    assert (
        "Shorter than minimum length 1."
        in response.json["message"]["combined_sensor_data_description"]["source-type"][
            0
        ]
    )


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
    sensor = setup_api_test_data["some gas sensor"]
    post_data_response = client.post(
        url_for("SensorAPI:post_data", id=sensor.id),
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
            "PT25M",
            "_schema",
            "Resolution of 0:04:10 is incompatible",
        ),
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
    sensor = setup_api_test_data["some gas sensor"]
    post_data[request_field] = new_value

    response = client.post(
        url_for("SensorAPI:post_data", id=sensor.id),
        json=post_data,
    )
    print(response.json)
    assert response.status_code == 422
    assert (
        error_text
        in response.json["message"]["combined_sensor_data_description"][error_field][0]
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
@pytest.mark.parametrize(
    "offclock_start, precise_start, precise_end, values, expected_values",
    [
        (
            "2021-06-08T00:00:40+02:00",
            "2021-06-08T00:00:00+02:00",
            "2021-06-08T01:00:00+02:00",
            [-11.28] * 6,
            [-11.28] * 6,
        ),
        (
            "2021-06-09T00:00:40+02:00",
            "2021-06-09T00:00:00+02:00",
            "2021-06-09T01:00:00+02:00",
            [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200],
            [150, 350, 550, 750, 950, 1150],
        ),
    ],
)
def test_post_non_instantaneous_sensor_data_floor(
    client,
    setup_api_test_data,
    requesting_user,
    offclock_start,
    precise_start,
    precise_end,
    values,
    expected_values,
):
    post_data = make_sensor_data_request_for_gas_sensor(
        num_values=len(values), unit="m³/h"
    )
    post_data["start"] = offclock_start
    post_data["values"] = values
    sensor = setup_api_test_data["some gas sensor"]

    assert (
        len(sensor.search_beliefs(precise_start, precise_end)) == 0
    ), "No beliefs were expected before we post our test data."

    response = client.post(
        url_for("SensorAPI:post_data", id=sensor.id),
        json=post_data,
    )

    assert response.status_code == 200

    new_data = sensor.search_beliefs(precise_start, precise_end).reset_index()
    assert len(new_data) == 6
    assert list(new_data["event_start"]) == [
        pd.Timestamp(precise_start),
        pd.Timestamp(precise_start) + pd.Timedelta(minutes=10),
        pd.Timestamp(precise_start) + pd.Timedelta(minutes=20),
        pd.Timestamp(precise_start) + pd.Timedelta(minutes=30),
        pd.Timestamp(precise_start) + pd.Timedelta(minutes=40),
        pd.Timestamp(precise_start) + pd.Timedelta(minutes=50),
    ]
    assert new_data["event_value"].to_list() == expected_values


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_post_non_instantaneous_sensor_data_with_zero_duration_single_value(
    client, setup_api_test_data, requesting_user
):
    post_data = make_sensor_data_request_for_gas_sensor(
        num_values=1,
        duration="PT0M",
        unit="m³/h",
    )
    sensor = setup_api_test_data["some gas sensor"]

    response = client.post(
        url_for("SensorAPI:post_data", id=sensor.id),
        json=post_data,
    )

    assert response.status_code == 422
    assert (
        "Cannot infer a non-zero resolution from one value over zero duration"
        in response.json["message"]["combined_sensor_data_description"]["_schema"][0]
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_post_sensor_data_twice(client, setup_api_test_data, requesting_user, db):
    sensor = setup_api_test_data["some gas sensor"]
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
        url_for("SensorAPI:post_data", id=sensor.id),
        json=post_data,
    )
    print(response.json)
    assert response.status_code == 200

    # Check that 2nd time posting the same data succeeds informatively
    response = client.post(
        url_for("SensorAPI:post_data", id=sensor.id),
        json=post_data,
    )
    print(response.json)
    assert response.status_code == 200
    assert "data has already been received" in response.json["message"]

    # Check that replacing data fails informatively
    post_data["values"][0] = 100
    response = client.post(
        url_for("SensorAPI:post_data", id=sensor.id),
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
        num_values=num_values,
        unit="°C",
        duration="PT0H",
    )
    sensor = setup_api_test_data["empty temperature sensor"]
    rows = len(sensor.search_beliefs())

    # Check that 1st time posting the data succeeds
    response = client.post(
        url_for("SensorAPI:post_data", id=sensor.id),
        json=post_data,
    )

    assert response.status_code == status_code
    if status_code == 422:
        assert (
            response.json["message"]["combined_sensor_data_description"]["_schema"][0]
            == message
        )
    else:
        assert response.json["message"] == message

    assert len(sensor.search_beliefs()) - rows == saved_rows
