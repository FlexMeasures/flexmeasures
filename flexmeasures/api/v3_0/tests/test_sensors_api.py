from __future__ import annotations


from flask import url_for


from flexmeasures import Sensor
from flexmeasures.api.tests.utils import get_auth_token


def test_fetch_one_sensor(
    client,
    setup_api_test_data: dict[str, Sensor],
):
    sensor_id = 1
    assert_response = {
        "name": "some gas sensor",
        "unit": "m³/h",
        "entity_address": "ea1.2023-08.localhost:fm1.1",
        "event_resolution": 10,
        "generic_asset_id": 4,
        "timezone": "UTC",
        "status": 200,
    }
    headers = make_headers_for("test_supplier_user_4@seita.nl", client)
    response = client.get(
        url_for("SensorAPI:fetch_one", id=sensor_id),
        headers=headers,
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    assert response.json == assert_response


def make_headers_for(user_email: str | None, client) -> dict:
    headers = {"content-type": "application/json"}
    if user_email:
        headers["Authorization"] = get_auth_token(client, user_email, "testtest")
    return headers
