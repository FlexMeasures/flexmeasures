from flask import url_for
import pytest

from bvp.api.common.responses import request_processed, invalid_horizon
from bvp.api.tests.utils import get_auth_token, message_replace_name_with_ea
from bvp.api.v1_1.tests.utils import message_for_get_prognosis
from bvp.data.auth_setup import UNAUTH_ERROR_STATUS


@pytest.mark.parametrize("query", [{}, {"access": "Prosumer"}])
def test_get_service(client, query):
    get_service_response = client.get(
        url_for("bvp_api_v1_1.get_service"),
        query_string=query,
        headers={"content-type": "application/json"},
    )
    print(get_service_response.json)
    assert get_service_response.status_code == 200
    assert get_service_response.json["type"] == "GetServiceResponse"
    assert get_service_response.json["status"] == request_processed()[0]["status"]
    if "access" in query:
        for service in get_service_response.json["services"]:
            assert "Prosumer" in service["access"]


def test_unauthorized_prognosis_request(client):
    get_prognosis_response = client.get(
        url_for("bvp_api_v1_1.get_prognosis"),
        query_string=message_for_get_prognosis(),
        headers={"content-type": "application/json"},
    )
    print(get_prognosis_response.json)
    assert get_prognosis_response.status_code == 401
    assert get_prognosis_response.json["type"] == "GetPrognosisResponse"
    assert get_prognosis_response.json["status"] == UNAUTH_ERROR_STATUS


@pytest.mark.parametrize(
    "message",
    [
        message_for_get_prognosis(no_horizon=True),
        message_for_get_prognosis(invalid_horizon=True),
    ],
)
def test_invalid_or_no_horizon(client, message):
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    get_prognosis_response = client.get(
        url_for("bvp_api_v1_1.get_prognosis"),
        query_string=message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print(get_prognosis_response.json)
    assert get_prognosis_response.status_code == 400
    assert get_prognosis_response.json["type"] == "GetPrognosisResponse"
    assert get_prognosis_response.json["status"] == invalid_horizon()[0]["status"]


def test_no_data(client):
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    get_prognosis_response = client.get(
        url_for("bvp_api_v1_1.get_prognosis"),
        query_string=message_replace_name_with_ea(
            message_for_get_prognosis(no_data=True)
        ),
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print(get_prognosis_response.json)
    assert get_prognosis_response.status_code == 200
    assert get_prognosis_response.json["type"] == "GetPrognosisResponse"
    # assert get_prognosis_response.json["values"] == []


@pytest.mark.parametrize(
    "message",
    [
        message_for_get_prognosis(single_connection=False),
        message_for_get_prognosis(single_connection=True),
        message_for_get_prognosis(no_resolution=True),
    ],
)
def test_get_prognosis(client, message):
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    get_prognosis_response = client.get(
        url_for("bvp_api_v1_1.get_prognosis"),
        query_string=message_replace_name_with_ea(message),
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print(get_prognosis_response.json)
    assert get_prognosis_response.status_code == 200
    if "groups" in get_prognosis_response.json:
        assert get_prognosis_response.json["groups"][0]["values"] == [
            300,
            300,
            300,
            300,
            300,
            300,
        ]
    else:
        assert get_prognosis_response.json["values"] == [300, 300, 300, 300, 300, 300]
