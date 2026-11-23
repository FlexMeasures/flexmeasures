"""
Job status endpoints check read access on the job's own asset or sensor,
not only on the sensor named in the URL.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytz
import pytest
from flask import url_for
from rq.job import Job

from flexmeasures.data.services.scheduling import create_scheduling_job


def _foreign_scheduling_job(sensor):
    timezone = pytz.timezone("Europe/Amsterdam")
    start = timezone.localize(datetime(2015, 1, 2))
    return create_scheduling_job(
        asset_or_sensor=sensor,
        start=start,
        end=start + timedelta(days=1),
        belief_time=start,
        resolution=timedelta(minutes=15),
        flex_model={"roundtrip-efficiency": "98%", "storage-efficiency": 0.999},
    )


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        (
            "test_dummy_user_3@seita.nl",
            403,
        ),  # can read the public price sensor, not the battery
        ("test_prosumer_user@seita.nl", 202),  # owns the battery
    ],
    indirect=["requesting_user"],
)
def test_get_schedule_checks_read_access_on_the_jobs_own_sensor(
    app,
    add_market_prices,
    add_battery_assets,
    battery_soc_sensor,
    keep_scheduling_queue_empty,
    clean_redis,
    requesting_user,
    expected_status_code,
):
    """A user who can read some sensor may not use it to look up the status of another account's job."""
    battery_power = add_battery_assets["Test battery"].sensors[0]
    job = _foreign_scheduling_job(battery_power)
    readable_sensor = add_market_prices["epex_da"]  # public

    with app.test_client() as client:
        response = client.get(
            url_for("SensorAPI:get_schedule", id=readable_sensor.id, uuid=job.id),
            query_string={"duration": "PT24H"},
        )

    assert response.status_code == expected_status_code, response.json
    if expected_status_code == 403:
        assert response.json["status"] == "INVALID_SENDER"
    else:
        assert response.json["status"] == "QUEUED"


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        ("test_prosumer_user@seita.nl", 403),
        ("test_admin_reader_user@seita.nl", 200),
    ],
    indirect=["requesting_user"],
)
def test_get_job_status_without_asset_or_sensor_needs_admin_access(
    app,
    setup_roles_users,
    keep_scheduling_queue_empty,
    clean_redis,
    requesting_user,
    expected_status_code,
):
    """A job whose asset or sensor is unknown (e.g. deleted) is not readable by any logged-in user."""
    job = Job.create(
        func=len,
        args=([],),
        connection=app.queues["scheduling"].connection,
        origin="scheduling",
        meta={"asset_or_sensor": None, "sensor_id": None},
    )
    job.set_status("finished")
    job.save()

    with app.test_client() as client:
        response = client.get(url_for("JobAPI:get_job_status", uuid=job.id))

    assert response.status_code == expected_status_code, response.json
