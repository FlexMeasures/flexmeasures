import pytest

from flask import url_for

from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.dev.tests.utils import make_sensor_data_request
from flexmeasures.data.models.time_series import TimedBelief, Sensor


@pytest.mark.parametrize(
    "num_values, expected_num_values",
    [
        (6, 6),
        (3, 6),  # upsample
        (1, 6),  # upsample single value sent as float rather than list of floats
    ],
)
def test_post_sensor_data(
    client, setup_api_fresh_test_data, num_values, expected_num_values
):
    post_data = make_sensor_data_request(num_values=num_values)
    sensor = Sensor.query.filter(Sensor.name == "some gas sensor").one_or_none()
    beliefs_before = TimedBelief.query.filter(TimedBelief.sensor_id == sensor.id).all()
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
    beliefs = TimedBelief.query.filter(TimedBelief.sensor_id == sensor.id).all()
    print(f"BELIEFS AFTER: {beliefs}")
    assert len(beliefs) == expected_num_values
    assert beliefs[0].event_value == -11.28
