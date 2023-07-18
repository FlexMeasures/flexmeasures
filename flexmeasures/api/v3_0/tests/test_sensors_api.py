from __future__ import annotations


from flask import url_for


from flexmeasures import Sensor
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v3_0.tests.utils import get_sensor_post_data


def test_fetch_one_sensor(
    client,
    setup_api_test_data: dict[str, Sensor],
):
    sensor_id = 1
    assert_response = {
        "name": "some gas sensor",
        "unit": "m³/h",
        "entity_address": "ea1.2023-08.localhost:fm1.1",
        # "event_resolution": 10, #remove
        "resolution": "PT10M",
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


def test_post_a_sensor(client, setup_api_test_data):
    """
    Post one extra asset, as an admin user.
    TODO: Soon we'll allow creating assets on an account-basis, i.e. for users
          who have the user role "account-admin" or something similar. Then we'll
          test that here.
    """
    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    post_data = get_sensor_post_data()
    print(post_data)
    post_sensor_response = client.post(
        url_for("SensorAPI:post"),
        json=post_data,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_sensor_response.json)
    assert post_sensor_response.status_code == 201
    assert post_sensor_response.json["name"] == "power"

    sensor: Sensor = Sensor.query.filter_by(name="power").one_or_none()
    assert sensor is not None
    assert sensor.unit == "kWh"


# db.session.query(GenericAsset)
# GenericAsset.query
# .filter(GenericAsset.name == "hoi")
# .filter_by(name="hoi")


# Sensor.query.filter(GenericAsset.name == "hoi")

# .filter(Sensor.generic_asset_id == GenericAsset.id).join(GenericAsset)

# .all()
# .one_or_none()
# .first()
# .count()

# Sensor.query.join(GenericAsset).filter(GenericAsset.id==4).all()

# Sensor.query.join(GenericAsset).filter(Sensor.generic_asset_id == GenericAsset.id, GenericAsset.account_id==2).all()

# class GenericAsset(db.model)
