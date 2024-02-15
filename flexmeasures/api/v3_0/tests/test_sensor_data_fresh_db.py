from __future__ import annotations

import pytest
from flask import url_for
from timely_beliefs.tests.utils import equal_lists
from sqlalchemy import select

from flexmeasures import Sensor, Source
from flexmeasures.api.v3_0.tests.utils import make_sensor_data_request_for_gas_sensor
from flexmeasures.data.models.time_series import TimedBelief


@pytest.mark.parametrize(
    "num_values, expected_num_values, unit, include_a_null, expected_value, expected_status",
    [
        (6, 6, "m³/h", False, -11.28, 200),
        (6, 5, "m³/h", True, -11.28, 200),  # NaN value does not enter database
        (6, 6, "m³", False, 6 * -11.28, 200),  # 6 * 10-min intervals per hour
        (6, 6, "l/h", False, -11.28 / 1000, 200),  # 1 m³ = 1000 l
        (3, 6, "m³/h", False, -11.28, 200),  # upsample from 20-min intervals
        (
            1,
            6,
            "m³/h",
            False,
            -11.28,
            200,
        ),  # upsample from single value for 1-hour interval, sent as float rather than list of floats
        (
            4,
            0,
            "m³/h",
            False,
            None,
            422,
        ),  # failed to resample from 15-min intervals to 10-min intervals
        (
            10,
            0,
            "m³/h",
            False,
            None,
            422,
        ),  # failed to resample from 6-min intervals to 10-min intervals
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_post_sensor_data(
    client,
    setup_api_fresh_test_data,
    num_values,
    expected_num_values,
    unit,
    include_a_null,
    expected_value,
    expected_status,
    requesting_user,
    db,
):
    post_data = make_sensor_data_request_for_gas_sensor(
        num_values=num_values, unit=unit, include_a_null=include_a_null
    )
    sensor: Sensor = db.session.execute(
        select(Sensor).filter_by(name="some gas sensor")
    ).scalar_one_or_none()
    filters = (
        TimedBelief.sensor_id == sensor.id,
        TimedBelief.event_start >= post_data["start"],
    )
    beliefs_before = db.session.scalars(select(TimedBelief).filter(*filters)).all()
    print(f"BELIEFS BEFORE: {beliefs_before}")
    assert len(beliefs_before) == 0

    response = client.post(
        url_for("SensorAPI:post_data"),
        json=post_data,
    )
    print(response.json)
    assert response.status_code == expected_status
    beliefs = db.session.scalars(select(TimedBelief).filter(*filters)).all()
    print(f"BELIEFS AFTER: {beliefs}")
    assert len(beliefs) == expected_num_values
    # check that values are scaled to the sensor unit correctly
    assert equal_lists(
        [b.event_value for b in beliefs], [expected_value] * expected_num_values
    )


@pytest.mark.parametrize("requesting_user", ["improper_user@seita.nl"], indirect=True)
def test_auto_fix_missing_registration_of_user_as_data_source(
    client,
    setup_api_fresh_test_data,
    setup_user_without_data_source,
    requesting_user,
    db,
):
    """Try to post sensor data as a user that has not been properly registered as a data source.
    The API call should succeed and the user should be automatically registered as a data source.
    """

    # Make sure the user is not yet registered as a data source
    data_source = db.session.execute(
        select(Source).filter_by(user=setup_user_without_data_source)
    ).scalar_one_or_none()
    assert data_source is None

    post_data = make_sensor_data_request_for_gas_sensor(
        num_values=6, unit="m³/h", include_a_null=False
    )
    response = client.post(
        url_for("SensorAPI:post_data"),
        json=post_data,
    )
    assert response.status_code == 200

    # Make sure the user is now registered as a data source
    data_source = db.session.execute(
        select(Source).filter_by(user=setup_user_without_data_source)
    ).scalar_one_or_none()
    assert data_source is not None
