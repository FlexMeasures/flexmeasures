from flask import url_for

from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.data.models.time_series import TimedBelief

post_data = {
    "type": "PostSensorDataRequest",
    "connection": "ea1.2021-01.io.flexmeasures:fm1.3",
    "values": [-11.28, -11.28, -11.28, -11.28, -11.28, -11.28],
    "start": "2021-06-07T00:00:00+02:00",
    "duration": "PT1H",
    "unit": "m³/h",
}


def test_post_sensor_data(client, db):
    beliefs_before = TimedBelief.query.filter(TimedBelief.sensor_id == 3).all()
    print(f"BELIEFS BEFORE: {beliefs_before}")
    assert len(beliefs_before) == 0
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    response = client.post(
        url_for("post_sensor_data"),
        json=post_data,
        headers={"Authorization": auth_token},
    )
    print(response.json)
    assert response.status_code == 200
    beliefs = TimedBelief.query.filter(TimedBelief.sensor_id == 3).all()
    print(f"BELIEFS AFTER: {beliefs}")
    assert len(beliefs) == 6
    assert beliefs[0].event_value == -11.28


# TODO:
# - test with a different valid event resolution
# - test with different role
# - test with more data
# - test with wrong unit
# - test with invalid event resolution
