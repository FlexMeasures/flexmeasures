import pytest
from flask import url_for

from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.dev.tests.utils import make_sensor_data_request_for_gas_sensor
from flexmeasures.data.models.time_series import TimedBelief, Sensor


@pytest.mark.parametrize(
    "num_values, expected_num_values, unit, expected_value",
    [
        (6, 6, "m³/h", -11.28),
        (6, 6, "m³", 6 * -11.28),  # 6 * 10-min intervals per hour
        (6, 6, "l/h", -11.28 / 1000),  # 1 m³ = 1000 l
        (3, 6, "m³/h", -11.28),  # upsample to 20-min intervals
        (
            1,
            6,
            "m³/h",
            -11.28,
        ),  # upsample to single value for 1-hour interval, sent as float rather than list of floats
    ],
)
def test_post_sensor_data(
    client,
    setup_api_fresh_test_data,
    num_values,
    expected_num_values,
    unit,
    expected_value,
):
    post_data = make_sensor_data_request_for_gas_sensor(
        num_values=num_values, unit=unit
    )
    sensor = Sensor.query.filter(Sensor.name == "some gas sensor").one_or_none()
    beliefs_before = TimedBelief.query.filter(TimedBelief.sensor_id == sensor.id).all()
    print(f"BELIEFS BEFORE: {beliefs_before}")
    assert len(beliefs_before) == 0

    auth_token = get_auth_token(client, "test_prosumer_user@seita.nl", "testtest")
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
    # check that values are scaled to the sensor unit correctly
    assert pytest.approx(beliefs[0].event_value - expected_value) == 0
