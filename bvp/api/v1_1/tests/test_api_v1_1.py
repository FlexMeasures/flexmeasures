import json

from flask import url_for
import pytest
from datetime import timedelta
from isodate import parse_duration, parse_datetime
import pandas as pd

from bvp.api.common.responses import request_processed, invalid_horizon
from bvp.api.common.utils.validators import validate_entity_address
from bvp.api.tests.utils import get_auth_token
from bvp.api.common.utils.api_utils import message_replace_name_with_ea
from bvp.api.v1_1.tests.utils import (
    message_for_get_prognosis,
    message_for_post_price_data,
)
from bvp.data.auth_setup import UNAUTH_ERROR_STATUS
from bvp.data.config import db
from bvp.data.models.markets import Market, Price


@pytest.mark.parametrize("query", [{}, {"access": "Prosumer"}])
def test_get_service(client, query):
    get_service_response = client.get(
        url_for("bvp_api_v1_1.get_service"),
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


def test_unauthorized_prognosis_request(client):
    get_prognosis_response = client.get(
        url_for("bvp_api_v1_1.get_prognosis"),
        query_string=message_for_get_prognosis(),
        headers={"content-type": "application/json"},
    )
    print("Server responded with:\n%s" % get_prognosis_response.json)
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
    print("Server responded with:\n%s" % get_prognosis_response.json)
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
    print("Server responded with:\n%s" % get_prognosis_response.json)
    assert get_prognosis_response.status_code == 200
    assert get_prognosis_response.json["type"] == "GetPrognosisResponse"
    assert get_prognosis_response.json["values"] == []


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
    print("Server responded with:\n%s" % get_prognosis_response.json)
    assert get_prognosis_response.status_code == 200
    if "groups" in get_prognosis_response.json:
        assert get_prognosis_response.json["groups"][0]["values"] == [
            300,
            301,
            302,
            303,
            304,
            305,
        ]
    else:
        assert get_prognosis_response.json["values"] == [300, 301, 302, 303, 304, 305]


@pytest.mark.parametrize("post_message", [message_for_post_price_data()])
def test_post_price_data(client, post_message):
    """
    Try to post price data as a logged-in test user with the Suppler role, which should succeed.
    """

    # post meter data
    auth_token = get_auth_token(client, "test_supplier@seita.nl", "testtest")
    post_price_data_response = client.post(
        url_for("bvp_api_v1_1.post_price_data"),
        data=json.dumps(post_message),
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_price_data_response.json)
    assert post_price_data_response.status_code == 200
    assert post_price_data_response.json["type"] == "PostPriceDataResponse"

    # verify the data ended up in the database
    start = parse_datetime(post_message["start"])
    end = start + parse_duration(post_message["duration"])
    values = post_message["values"]
    market = validate_entity_address(post_message["market"], "market")
    market_name = market["market_name"]
    # Todo: get data resolution for the market or use the Price.collect function
    resolution = timedelta(minutes=15)
    query = (
        db.session.query(Price.value, Market.name)
        .filter((Price.datetime > start - resolution) & (Price.datetime < end))
        .join(Market)
        .filter(Market.name == market_name)
    )
    df = pd.read_sql(query.statement, db.session.bind)
    assert df.value.tolist() == values
