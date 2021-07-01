import pytest

from flask import url_for

from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.dev.tests.utils import make_sensor_data_request
from flexmeasures.data.models.time_series import TimedBelief


@pytest.mark.parametrize(
    "post_data, expected_num_values",
    [
        (make_sensor_data_request(), 6),
        (make_sensor_data_request(num_values=3), 6),  # upsample
    ],
)
def test_post_sensor_data(
    client, setup_api_fresh_test_data, post_data, expected_num_values
):
    beliefs_before = TimedBelief.query.filter(TimedBelief.sensor_id == 1).all()
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
    beliefs = TimedBelief.query.filter(TimedBelief.sensor_id == 1).all()
    print(f"BELIEFS AFTER: {beliefs}")
    assert len(beliefs) == expected_num_values
    assert beliefs[0].event_value == -11.28
