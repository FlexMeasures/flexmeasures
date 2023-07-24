from __future__ import annotations


from flask import url_for


from flexmeasures import Sensor
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v3_0.tests.utils import get_sensor_post_data
from flexmeasures.data.schemas.sensors import SensorSchema

sensor_schema = SensorSchema()


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
    assert response.status_code == 200
    assert response.json["name"] == "some gas sensor"
    assert response.json["unit"] == "m³/h"
    assert response.json["generic_asset_id"] == 4
    assert response.json["timezone"] == "UTC"
    assert response.json["resolution"] == "PT10M"


def make_headers_for(user_email: str | None, client) -> dict:
    headers = {"content-type": "application/json"}
    if user_email:
        headers["Authorization"] = get_auth_token(client, user_email, "testtest")
    return headers


def test_post_a_sensor(client, setup_api_test_data):
    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    post_data = get_sensor_post_data()
    post_sensor_response = client.post(
        url_for("SensorAPI:post"),
        json=post_data,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )

    assert post_sensor_response.status_code == 201
    assert post_sensor_response.json["name"] == "power"
    assert post_sensor_response.json["resolution"] == "PT1H"

    sensor: Sensor = Sensor.query.filter_by(name="power").one_or_none()
    assert sensor is not None
    assert sensor.unit == "kWh"

    sensor_edit_response = client.patch(
        url_for("SensorAPI:patch", id=sensor.id),
        headers={"content-type": "application/json", "Authorization": auth_token},
        json={
            "name": "POWER",
        },
    )

    assert sensor_edit_response.json["name"] == "POWER"

