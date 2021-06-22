from flask import url_for

from flexmeasures.api.tests.utils import get_auth_token

post_data = {
    "type": "PostSensorDataRequest",
    "connection": "ea1.2021-01.io.flexmeasures:fm1.3",
    "values": [-11.28, -11.28, -11.28, -11.28, -11.28, -11.28],
    "start": "2021-06-07T00:00:00+02:00",
    "duration": "PT1H",
    "unit": "m³/h",
}


def test_post_sensor_data(client, db):
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    response = client.post(
        url_for("post_sensor_data"),
        json=post_data,
        headers={"Authorization": auth_token},
    )
    print(response.json)
    assert response.status_code == 200


# TODO:
# - check that data is stored
# - test with a different valid event resolution
# - test with different role
# - test with more data
# - test with wrong unit
# - test with invalid event resolution
