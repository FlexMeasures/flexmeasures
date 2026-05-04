"""Tests for the unified job status endpoint (GET /api/v3_0/jobs/<uuid>)."""

from __future__ import annotations

import pytest
from flask import url_for
from rq.job import Job, JobStatus

from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.tests.test_scheduling_repeated_jobs_fresh_db import (
    FailingScheduler,
)
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
    """Requesting a non-existent job UUID should return 404."""
    with app.test_client() as client:
        response = client.get(
            url_for("JobAPI:get_job_status", uuid="non-existent-uuid"),
        )
    assert response.status_code == 404
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
    """A job that is still queued should be reported as QUEUED with metadata fields."""
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
    data = response.json
    assert data["status"] == "QUEUED"
    assert "waiting" in data["message"].lower()
    # metadata fields present
    assert "func_name" in data
    assert "origin" in data
    assert data["origin"] == "scheduling"
    # enqueued_at is set when a job is queued; started_at and ended_at are not yet
    assert data["enqueued_at"] is not None
    assert data["started_at"] is None
    assert data["ended_at"] is None
    # result is not yet available
    assert data["result"] is None
    assert data["exc_info"] is None


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_job_status_started(
    app,
    add_market_prices,
    add_battery_assets,
    battery_soc_sensor,
    keep_scheduling_queue_empty,
    requesting_user,
):
    """A job whose status has been set to STARTED should be reported as STARTED."""
    sensor = add_battery_assets["Test battery"].sensors[0]
    message = message_for_trigger_schedule()

    with app.test_client() as client:
        trigger_response = client.post(
            url_for("SensorAPI:trigger_schedule", id=sensor.id),
            json=message,
        )
        assert trigger_response.status_code == 200
        job_id = trigger_response.json["schedule"]

        # simulate the job being picked up by a worker
        job = Job.fetch(job_id, connection=app.queues["scheduling"].connection)
        job.set_status(JobStatus.STARTED)

        response = client.get(
            url_for("JobAPI:get_job_status", uuid=job_id),
        )

    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    data = response.json
    assert data["status"] == "STARTED"
    assert "in progress" in data["message"].lower()
    # metadata fields present
    assert "func_name" in data
    assert data["origin"] == "scheduling"
    # enqueued_at is set; ended_at is not yet available
    assert data["enqueued_at"] is not None
    assert data["ended_at"] is None
    # result is not yet available
    assert data["result"] is None
    assert data["exc_info"] is None


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
    """After the job has been processed the response should include timing fields."""
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
    data = response.json
    assert data["status"] == "FINISHED"
    assert "finished" in data["message"].lower()
    # metadata fields present
    assert "func_name" in data
    assert data["origin"] == "scheduling"
    # timing fields
    assert data["enqueued_at"] is not None
    assert data["started_at"] is not None
    assert data["ended_at"] is not None
    # scheduling jobs return True on success; result must be present in the response
    assert data["result"] is not None
    assert data["exc_info"] is None


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_job_status_failed_custom_scheduler_includes_exc_info(
    app,
    db,
    add_market_prices,
    add_battery_assets,
    battery_soc_sensor,
    keep_scheduling_queue_empty,
    requesting_user,
    monkeypatch,
):
    def fail_with_assertion(self):
        assert 1 == 2

    monkeypatch.setattr(FailingScheduler, "compute", fail_with_assertion)

    sensor = add_battery_assets["Test battery"].sensors[0]
    sensor.attributes["custom-scheduler"] = {
        "module": "flexmeasures.data.tests.test_scheduling_repeated_jobs_fresh_db",
        "class": "FailingScheduler",
    }
    db.session.add(sensor)
    db.session.commit()

    with app.test_client() as client:
        trigger_response = client.post(
            url_for("SensorAPI:trigger_schedule", id=sensor.id),
            json=message_for_trigger_schedule(),
        )
        assert trigger_response.status_code == 200
        job_id = trigger_response.json["schedule"]

        work_on_rq(
            app.queues["scheduling"],
            exc_handler=handle_scheduling_exception,
            max_jobs=1,
        )

        response = client.get(url_for("JobAPI:get_job_status", uuid=job_id))

    assert response.status_code == 200
    data = response.json
    assert data["status"] == "FAILED"
    assert "assert 1 == 2" in data["message"]
    assert "AssertionError: assert 1 == 2" in data["exc_info"]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_job_status_failed_infeasible_schedule_includes_exc_info(
    app,
    add_market_prices,
    add_charging_station_assets,
    keep_scheduling_queue_empty,
    requesting_user,
):
    charging_station = add_charging_station_assets["Test charging station"].sensors[0]
    message = message_for_trigger_schedule(with_targets=True, realistic_targets=False)

    with app.test_client() as client:
        trigger_response = client.post(
            url_for("SensorAPI:trigger_schedule", id=charging_station.id),
            json=message,
        )
        assert trigger_response.status_code == 200
        job_id = trigger_response.json["schedule"]

        work_on_rq(
            app.queues["scheduling"],
            exc_handler=handle_scheduling_exception,
            max_jobs=1,
        )

        response = client.get(url_for("JobAPI:get_job_status", uuid=job_id))

    assert response.status_code == 200
    data = response.json
    assert data["status"] == "FAILED"
    assert "infeasible problem" in data["message"].lower()
    assert (
        "ValueError: The input data yields an infeasible problem." in data["exc_info"]
    )


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
