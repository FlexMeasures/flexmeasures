from datetime import timedelta

from flask import url_for
import isodate
import pandas as pd
import pytest

from flexmeasures.api.common.responses import (
    invalid_domain,
    invalid_sender,
    invalid_unit,
    request_processed,
    unrecognized_connection_group,
)
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.common.utils.api_utils import message_replace_name_with_ea
from flexmeasures.api.common.utils.validators import validate_user_sources
from flexmeasures.api.v1.tests.utils import (
    message_for_get_meter_data,
    message_for_post_meter_data,
    verify_power_in_db,
)
from flexmeasures.auth.error_handling import UNAUTH_ERROR_STATUS
from flexmeasures.data.models.time_series import Sensor


@pytest.mark.parametrize("query", [{}, {"access": "Prosumer"}])
def test_get_service(client, query):
    get_service_response = client.get(
        url_for("flexmeasures_api_v1.get_service"),
        query_string=query,
        headers={"content-type": "application/json"},
    )
    print("Server responded with:\n%s" % get_service_response.json)
    assert get_service_response.status_code == 200
    assert get_service_response.json["type"] == "GetServiceResponse"
    assert get_service_response.json["status"] == request_processed()[0]["status"]
    if "access" in query:
        for service in get_service_response.json["services"]:
            assert "Prosumer" in service["access"]


def test_unauthorized_request(client):
    get_meter_data_response = client.get(
        url_for("flexmeasures_api_v1.get_meter_data"),
        query_string=message_for_get_meter_data(no_connection=True),
        headers={"content-type": "application/json"},
    )
    print("Server responded with:\n%s" % get_meter_data_response.json)
    assert get_meter_data_response.status_code == 401
    assert get_meter_data_response.json["type"] == "GetMeterDataResponse"
    assert get_meter_data_response.json["status"] == UNAUTH_ERROR_STATUS


def test_no_connection_in_get_request(client):
    get_meter_data_response = client.get(
        url_for("flexmeasures_api_v1.get_meter_data"),
        query_string=message_for_get_meter_data(no_connection=True),
        headers={
            "Authorization": get_auth_token(
                client, "test_prosumer_user@seita.nl", "testtest"
            )
        },
    )
    print("Server responded with:\n%s" % get_meter_data_response.json)
    assert get_meter_data_response.status_code == 400
    assert get_meter_data_response.json["type"] == "GetMeterDataResponse"
    assert (
        get_meter_data_response.json["status"]
        == unrecognized_connection_group()[0]["status"]
    )


def test_invalid_connection_in_get_request(client):
    get_meter_data_response = client.get(
        url_for("flexmeasures_api_v1.get_meter_data"),
        query_string=message_for_get_meter_data(invalid_connection=True),
        headers={
            "Authorization": get_auth_token(
                client, "test_prosumer_user@seita.nl", "testtest"
            )
        },
    )
    print("Server responded with:\n%s" % get_meter_data_response.json)
    assert get_meter_data_response.status_code == 400
    assert get_meter_data_response.json["type"] == "GetMeterDataResponse"
    assert get_meter_data_response.json["status"] == invalid_domain()[0]["status"]


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize(
    "message",
    [
        message_for_get_meter_data(no_unit=True),
        message_for_get_meter_data(invalid_unit=True),
    ],
)
def test_invalid_or_no_unit(client, method, message):
    if method == "GET":
        get_meter_data_response = client.get(
            url_for("flexmeasures_api_v1.get_meter_data"),
            query_string=message,
            headers={
                "Authorization": get_auth_token(
                    client, "test_prosumer_user@seita.nl", "testtest"
                )
            },
        )
    elif method == "POST":
        get_meter_data_response = client.post(
            url_for("flexmeasures_api_v1.get_meter_data"),
            json=message,
            headers={
                "Authorization": get_auth_token(
                    client, "test_prosumer_user@seita.nl", "testtest"
                )
            },
        )
    else:
        get_meter_data_response = []
    assert get_meter_data_response.status_code == 400
    assert get_meter_data_response.json["type"] == "GetMeterDataResponse"
    assert (
        get_meter_data_response.json["status"]
        == invalid_unit("power", ["MW"])[0]["status"]
    )


@pytest.mark.parametrize(
    "user_email, get_message",
    [
        ["test_dummy_user_3@seita.nl", message_for_get_meter_data()],
        ["demo@seita.nl", message_for_get_meter_data(demo_connection=True)],
    ],
)
def test_invalid_sender_and_logout(client, user_email, get_message):
    """
    Tries to get meter data as a logged-in test user without any suitable
    account role, which should fail.
    Then tries to log out, which should succeed as a url direction.
    """

    # get meter data
    auth_token = get_auth_token(client, user_email, "testtest")
    get_meter_data_response = client.get(
        url_for("flexmeasures_api_v1.get_meter_data"),
        query_string=get_message,
        headers={"Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_meter_data_response.json)
    assert get_meter_data_response.status_code == 403
    assert get_meter_data_response.json["status"] == invalid_sender()[0]["status"]

    # log out
    logout_response = client.get(
        url_for("security.logout"),
        headers={"Authorization ": auth_token, "content-type": "application/json"},
    )
    assert logout_response.status_code == 302


def test_invalid_resolution_str(client):
    auth_token = get_auth_token(client, "test_prosumer_user@seita.nl", "testtest")
    query_string = message_for_get_meter_data()
    query_string["resolution"] = "15M"  # invalid
    get_meter_data_response = client.get(
        url_for("flexmeasures_api_v1.get_meter_data"),
        query_string=query_string,
        headers={"Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_meter_data_response.json)
    assert get_meter_data_response.status_code == 400
    assert get_meter_data_response.json["type"] == "GetMeterDataResponse"
    assert get_meter_data_response.json["status"] == "INVALID_RESOLUTION"


@pytest.mark.parametrize(
    "message",
    [
        message_for_get_meter_data(single_connection=True),
        message_for_get_meter_data(
            single_connection=True, source="Prosumer"
        ),  # sourced by a Prosumer
        message_for_get_meter_data(
            single_connection=True, source=["Prosumer", 109304]
        ),  # sourced by a Prosumer or user 109304
    ],
)
def test_get_meter_data(db, app, client, message):
    """Checks Charging Station 5, which has multi-sourced data for the same time interval:
    6 values from a Prosumer, and 6 values from a Supplier.

    All data should be in the database, and currently only the Prosumer data is returned.
    """
    message["connection"] = "CS 5"

    # set up frame with expected values, and filter by source if needed
    expected_values = pd.concat(
        [
            pd.DataFrame.from_dict(
                dict(
                    event_value=[(100.0 + i) for i in range(6)],
                    event_start=[
                        isodate.parse_datetime("2015-01-01T00:00:00Z")
                        + timedelta(minutes=15 * i)
                        for i in range(6)
                    ],
                    source_id=1,
                )
            ),
            pd.DataFrame.from_dict(
                dict(
                    event_value=[(1000.0 - 10 * i) for i in range(6)],
                    event_start=[
                        isodate.parse_datetime("2015-01-01T00:00:00Z")
                        + timedelta(minutes=15 * i)
                        for i in range(6)
                    ],
                    source_id=2,
                )
            ),
        ]
    )
    if "source" in message:
        source_ids = validate_user_sources(message["source"])
        expected_values = expected_values[expected_values["source_id"].isin(source_ids)]
    expected_values = expected_values.set_index(
        ["event_start", "source_id"]
    ).sort_index()

    # check whether conftest.py did its job setting up the database with expected values
    cs_5 = Sensor.query.filter(Sensor.name == "CS 5").one_or_none()
    verify_power_in_db(message, cs_5, expected_values, db, swapped_sign=True)

    # check whether the API returns the expected values (currently only the Prosumer data is returned)
    auth_token = get_auth_token(client, "test_prosumer_user@seita.nl", "testtest")
    get_meter_data_response = client.get(
        url_for("flexmeasures_api_v1.get_meter_data"),
        query_string=message_replace_name_with_ea(message),
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_meter_data_response.json)
    assert get_meter_data_response.status_code == 200
    assert get_meter_data_response.json["values"] == [(100.0 + i) for i in range(6)]


def test_post_meter_data_to_different_resolutions(app, client):
    """
    Tries to post meter data to assets with different event_resolutions, which is not accepted.
    """

    post_message = message_for_post_meter_data(different_target_resolutions=True)
    auth_token = get_auth_token(client, "test_prosumer_user@seita.nl", "testtest")
    post_meter_data_response = client.post(
        url_for("flexmeasures_api_v1.post_meter_data"),
        json=message_replace_name_with_ea(post_message),
        headers={"Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_meter_data_response.json)
    assert post_meter_data_response.json["type"] == "PostMeterDataResponse"
    assert post_meter_data_response.status_code == 400
    assert (
        "assets do not have matching resolutions"
        in post_meter_data_response.json["message"]
    )
    assert "CS 2" in post_meter_data_response.json["message"]
    assert "CS 4" in post_meter_data_response.json["message"]
    assert post_meter_data_response.json["status"] == "INVALID_RESOLUTION"
