import json

from flask import url_for

from bvp.api.v1.tests.utils import get_auth_token


def test_api_login_service_responds(client):

    # get meter data
    auth_token = get_auth_token(client, "test_user@seita.nl", "testtest")
    get_meter_data_response = client.get(
        url_for("bvp_api_v1.get_meter_data"),
        query_string={
            "start": "2015-01-01T00:00:00Z",
            "duration": "PT1H30M",
            "connection": "CS 1",
            "unit": "MW",
        },
        headers={"Authentication-Token": auth_token},
    )
    assert get_meter_data_response.status_code == 403

    logout_response = client.get(
        url_for("security.logout"),
        headers={
            "Authentication-Token": auth_token,
            "content-type": "application/json",
        },
    )
    assert logout_response.status_code == 302

    # get auth token
    auth_token = get_auth_token(client, "test_prosumer_user@seita.nl", "testtest")

    # post meter data
    test_values_for_asset_1_and_2 = [306.66, 306.66, 0, 0, 306.66, 306.66]
    test_values_for_asset_3 = [306.66, 0, 0, 0, 306.66, 306.66]
    post_meter_data_response = client.post(
        url_for("bvp_api_v1.post_meter_data"),
        data=json.dumps(
            {
                "type": "PostMeterDataRequest",
                "groups": [
                    {
                        "connections": ["CS 1", "CS 2"],
                        "values": test_values_for_asset_1_and_2,
                    },
                    {"connection": "CS 3", "values": test_values_for_asset_3},
                ],
                "start": "2015-01-01T00:00:00Z",
                "duration": "PT1H30M",
                "unit": "MW",
            }
        ),
        headers={
            "content-type": "application/json",
            "Authentication-Token": auth_token,
        },
    )
    print(post_meter_data_response.json)
    assert post_meter_data_response.status_code == 200

    # get meter data
    get_meter_data_response = client.get(
        url_for("bvp_api_v1.get_meter_data"),
        query_string={
            "start": "2015-01-01T00:00:00Z",
            "duration": "PT1H30M",
            "connection": "CS 1",
            "unit": "MW",
        },
        headers={"Authentication-Token": auth_token},
    )
    assert get_meter_data_response.status_code == 200
    assert get_meter_data_response.json["values"] == test_values_for_asset_1_and_2
