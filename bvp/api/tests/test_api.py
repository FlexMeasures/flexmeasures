import json

from flask import url_for

from bvp.api.tests.utils import get_auth_token


def _test_api_login_service_responds(client):

    # get meter data
    get_meter_data_response = client.get(
        url_for("bvp_api.get_meter_data"),
        query_string={
            "start": "2016-05-01T12:45:00Z",
            "duration": "PT1H30M",
            "connection": "wind-asset-1",
            "unit": "MW",
        },
        headers={
            "Authentication-Token": get_auth_token(
                client, "test_prosumer@seita.nl", "testtest"
            )
        },
    )
    assert get_meter_data_response.status_code == 401

    client.get(url_for("security.logout"))
    prosumer_auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")

    # post meter data
    test_values_for_wind_assets = [306.66, 306.66, 0, 0, 306.66, 306.66]
    test_values_for_solar_asset = [306.66, 0, 0, 0, 306.66, 306.66]
    post_meter_data_response = client.post(
        url_for("bvp_api.post_meter_data"),
        data=json.dumps(
            {
                "type": "PostMeterDataRequest",
                "groups": [
                    {
                        "connections": [
                            "ea1.2018-06.com.bvp.api:45:wind-asset-1",
                            "ea1.2018-06.com.bvp.api:45:wind-asset-2",
                        ],
                        "values": test_values_for_wind_assets,
                    },
                    {
                        "connection": "ea1.2018-06.com.bvp.api:45:solar-asset-1",
                        "values": test_values_for_solar_asset,
                    },
                ],
                "start": "2016-05-01T12:45:00Z",
                "duration": "PT1H30M",
                "unit": "MW",
            }
        ),
        headers={
            "content-type": "application/json",
            "Authentication-Token": prosumer_auth_token,
        },
    )
    assert post_meter_data_response.status_code == 200

    # get meter data
    get_meter_data_response = client.get(
        url_for("bvp_api.get_meter_data"),
        query_string={
            "start": "2016-05-01T12:45:00Z",
            "duration": "PT1H30M",
            "connection": "test-asset-1",
            "unit": "MW",
        },
        headers={"Authentication-Token": prosumer_auth_token},
    )
    assert get_meter_data_response.status_code == 200
    assert get_meter_data_response.json["values"] == test_values_for_wind_assets
