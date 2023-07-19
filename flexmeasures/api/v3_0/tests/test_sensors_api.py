from __future__ import annotations


from flask import url_for


from flexmeasures import Sensor
from flexmeasures.api.tests.utils import get_auth_token


def test_fetch_one_sensor(
    client,
    setup_api_test_data: dict[str, Sensor],
):
    sensor_id = 1
    headers = make_headers_for("test_supplier_user_4@seita.nl", client)
    response = client.get(
        url_for("SensorAPI:fetch_one", id=sensor_id),
        headers=headers,
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    assert response.json["name"] == "some gas sensor"
    assert response.json["unit"] == "m³/h"
    assert response.json["generic_asset_id"] == 4
    assert response.json["timezone"] == "UTC"


def make_headers_for(user_email: str | None, client) -> dict:
    headers = {"content-type": "application/json"}
    if user_email:
        headers["Authorization"] = get_auth_token(client, user_email, "testtest")
    return headers
