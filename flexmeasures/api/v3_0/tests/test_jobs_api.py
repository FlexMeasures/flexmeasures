"""Tests for the unified job status endpoint (GET /api/v3_0/jobs/<uuid>)."""

from __future__ import annotations

import pytest
from flask import url_for
from rq.job import Job

from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.utils.job_utils import work_on_rq
from flexmeasures.data.services.scheduling import handle_scheduling_exception


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_job_status_unknown_uuid(
    app,
    add_battery_assets,
    keep_scheduling_queue_empty,
    requesting_user,
):
    """Requesting a non-existent job UUID should return 400."""
    with app.test_client() as client:
        response = client.get(
            url_for("JobAPI:get_job_status", uuid="non-existent-uuid"),
        )
    assert response.status_code == 400
    assert "not found" in response.json["message"]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_job_status_queued(
    app,
    add_market_prices,
    add_battery_assets,
    battery_soc_sensor,
    keep_scheduling_queue_empty,
    requesting_user,
):
    """A job that is still queued should be reported as QUEUED."""
    sensor = add_battery_assets["Test battery"].sensors[0]
    message = message_for_trigger_schedule()

    with app.test_client() as client:
        # trigger a schedule job
        trigger_response = client.post(
            url_for("SensorAPI:trigger_schedule", id=sensor.id),
            json=message,
        )
        assert trigger_response.status_code == 200
        job_id = trigger_response.json["schedule"]

        # immediately query the generic job endpoint – job is still queued
        response = client.get(
            url_for("JobAPI:get_job_status", uuid=job_id),
        )

    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    assert response.json["status"] == "QUEUED"
    assert "waiting" in response.json["message"].lower()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_job_status_finished(
    app,
    add_market_prices,
    add_battery_assets,
    battery_soc_sensor,
    add_charging_station_assets,
    keep_scheduling_queue_empty,
    requesting_user,
    db,
):
    """After the job has been processed it should be reported as FINISHED."""
    sensor = add_battery_assets["Test battery"].sensors[0]
    message = message_for_trigger_schedule()

    with app.test_client() as client:
        trigger_response = client.post(
            url_for("SensorAPI:trigger_schedule", id=sensor.id),
            json=message,
        )
        assert trigger_response.status_code == 200
        job_id = trigger_response.json["schedule"]

        # run the scheduling job
        work_on_rq(app.queues["scheduling"], exc_handler=handle_scheduling_exception)
        job = Job.fetch(job_id, connection=app.queues["scheduling"].connection)
        assert job.is_finished

        # query the generic job endpoint
        response = client.get(
            url_for("JobAPI:get_job_status", uuid=job_id),
        )

    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    assert response.json["status"] == "FINISHED"
    assert "finished" in response.json["message"].lower()


def test_get_job_status_unauthenticated(
    app,
    add_battery_assets,
    keep_scheduling_queue_empty,
):
    """Unauthenticated requests should be rejected with 401."""
    with app.test_client() as client:
        response = client.get(
            url_for("JobAPI:get_job_status", uuid="any-uuid"),
        )
    assert response.status_code == 401
