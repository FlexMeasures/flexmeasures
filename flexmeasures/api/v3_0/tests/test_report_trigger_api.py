"""Tests for the report trigger endpoint (POST /api/v3_0/assets/<id>/reports/trigger)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from flask import url_for

from flexmeasures.data.models.time_series import Sensor


@pytest.fixture(scope="module")
def setup_report_sensors(db, add_battery_assets):
    """Add two (hourly) input sensors and a (two-hourly) report sensor to the battery asset."""
    battery = add_battery_assets["Test battery"]
    sensor_1 = Sensor(
        "input sensor 1", generic_asset=battery, event_resolution=timedelta(hours=1)
    )
    sensor_2 = Sensor(
        "input sensor 2", generic_asset=battery, event_resolution=timedelta(hours=1)
    )
    report_sensor = Sensor(
        "report sensor", generic_asset=battery, event_resolution=timedelta(hours=2)
    )
    db.session.add_all([sensor_1, sensor_2, report_sensor])
    db.session.flush()
    return sensor_1, sensor_2, report_sensor


def make_report_trigger_message(
    sensor_1: Sensor, sensor_2: Sensor, report_sensor: Sensor
) -> dict:
    """A PandasReporter message that adds up two sensors at a two-hour resolution."""
    return {
        "reporter": "PandasReporter",
        "config": {
            "required_input": [{"name": "sensor_1"}, {"name": "sensor_2"}],
            "required_output": [{"name": "df_agg"}],
            "transformations": [
                {
                    "df_input": "sensor_1",
                    "method": "add",
                    "args": ["@sensor_2"],
                    "df_output": "df_agg",
                },
                {"method": "resample_events", "args": ["2h"]},
            ],
        },
        "parameters": {
            "input": [
                {"name": "sensor_1", "sensor": sensor_1.id},
                {"name": "sensor_2", "sensor": sensor_2.id},
            ],
            "output": [{"name": "df_agg", "sensor": report_sensor.id}],
            "start": "2023-04-10T00:00:00+00:00",
            "end": "2023-04-10T10:00:00+00:00",
        },
    }


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        (None, 401),  # not logged in
        ("test_prosumer_user@seita.nl", 200),  # same account
        ("test_dummy_user_3@seita.nl", 403),  # different account
    ],
    indirect=["requesting_user"],
)
def test_trigger_report_auth(
    app,
    add_battery_assets,
    setup_report_sensors,
    clean_redis,
    requesting_user,
    expected_status_code,
):
    """Triggering a report requires create-children access to the asset (any account member)."""
    battery = add_battery_assets["Test battery"]
    message = make_report_trigger_message(*setup_report_sensors)
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=battery.id),
            json=message,
        )
    assert response.status_code == expected_status_code


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_report(
    app,
    add_battery_assets,
    setup_report_sensors,
    clean_redis,
    requesting_user,
):
    """A successful trigger queues a job on the reporting queue, which records how it was triggered."""
    battery = add_battery_assets["Test battery"]
    message = make_report_trigger_message(*setup_report_sensors)
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=battery.id),
            json=message,
        )
    assert response.status_code == 200
    assert response.json["status"] == "PROCESSED"
    job_id = response.json["report"]

    jobs = app.queues["reporting"].jobs
    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == job_id
    assert job.meta["trigger"] == {"origin": "API"}
    assert job.kwargs["parameters"]["output"] == message["parameters"]["output"]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
@pytest.mark.parametrize(
    "message_updates, expected_error_field",
    [
        # missing required timing fields
        ({"parameters": {"start": None, "end": None}}, "start"),
        # no output to save the report to
        ({"parameters": {"output": None}}, "output"),
        # unknown reporter class
        ({"reporter": "UnknownReporter"}, "UnknownReporter"),
        # invalid config for the reporter class
        ({"config": {"invalid_field": 1}}, "invalid_field"),
        # missing required fields altogether
        ({"reporter": None, "parameters": None}, "reporter"),
    ],
)
def test_trigger_report_with_invalid_message(
    app,
    add_battery_assets,
    setup_report_sensors,
    clean_redis,
    requesting_user,
    message_updates,
    expected_error_field,
):
    """Invalid trigger messages should yield a 422, and no job should be queued."""
    battery = add_battery_assets["Test battery"]
    message = make_report_trigger_message(*setup_report_sensors)

    # apply updates to the valid message (None means: remove the field)
    for field, update in message_updates.items():
        if update is None:
            del message[field]
        elif isinstance(update, dict):
            for subfield, subupdate in update.items():
                if subupdate is None:
                    del message[field][subfield]
                else:
                    message[field][subfield] = subupdate
        else:
            message[field] = update

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=battery.id),
            json=message,
        )
    assert response.status_code == 422
    assert expected_error_field in str(response.json)
    assert len(app.queues["reporting"].jobs) == 0
