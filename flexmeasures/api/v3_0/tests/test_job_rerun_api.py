"""Tests for re-running a failed job (POST /api/v3_0/jobs/<uuid>/rerun), and for offering it in the asset's job list."""

from __future__ import annotations

from uuid import uuid4

import pytest
from flask import url_for
from rq.job import Job, JobStatus
from sqlalchemy import select

from flexmeasures.api.v3_0.tests.utils import report_message
from flexmeasures.data.automations import execute_automation_job
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.services.data_sources import get_data_generator
from flexmeasures.utils.job_utils import work_on_rq


def fail_on_purpose():
    raise ValueError("This job fails on purpose.")


def failed_job(queue, meta: dict) -> Job:
    """Queue a job carrying the given metadata, and have a worker fail it."""
    job = queue.enqueue(fail_on_purpose, meta=meta)
    work_on_rq(queue, max_jobs=1)
    assert (
        job.get_status() == JobStatus.FAILED
    ), "the job should fail for the test to mean anything"
    return job


def battery_schedule_meta(sensor) -> dict:
    return {"asset_or_sensor": {"class": "Sensor", "id": sensor.id}}


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        (None, 401),
        ("test_prosumer_user@seita.nl", 202),
        # May read the battery, but not trigger schedules on it.
        ("test_admin_reader_user@seita.nl", 403),
        # May not even read the battery.
        ("test_dummy_user_3@seita.nl", 403),
    ],
    indirect=["requesting_user"],
)
def test_rerun_failed_schedule(
    app, db, add_battery_assets, clean_redis, requesting_user, expected_status_code
):
    sensor = add_battery_assets["Test battery"].sensors[0]
    job = failed_job(app.queues["scheduling"], battery_schedule_meta(sensor))

    with app.test_client() as client:
        response = client.post(url_for("JobAPI:rerun_job", uuid=job.id))

    assert response.status_code == expected_status_code
    audit_events = db.session.scalars(
        select(AssetAuditLog.event).where(
            AssetAuditLog.affected_asset_id == sensor.generic_asset_id
        )
    ).all()
    if expected_status_code == 202:
        assert response.json["job"] == job.id, "the job keeps its ID"
        assert (
            job.get_status() == JobStatus.QUEUED
        ), "the job is back in the scheduling queue"
        assert job.id in app.queues["scheduling"].job_ids
        assert f"Re-ran failed scheduling job {job.id}." in audit_events
    else:
        assert (
            job.get_status() == JobStatus.FAILED
        ), "a refused re-run leaves the job alone"
        assert f"Re-ran failed scheduling job {job.id}." not in audit_events


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        ("test_prosumer_user@seita.nl", 202),
        # May read the sensor, but not trigger forecasts on it.
        ("test_admin_reader_user@seita.nl", 403),
    ],
    indirect=["requesting_user"],
)
def test_rerun_failed_forecast(
    app, add_battery_assets, clean_redis, requesting_user, expected_status_code
):
    sensor = add_battery_assets["Test battery"].sensors[0]
    job = failed_job(app.queues["forecasting"], {"sensor_id": sensor.id})

    with app.test_client() as client:
        response = client.post(url_for("JobAPI:rerun_job", uuid=job.id))

    assert response.status_code == expected_status_code
    expected_job_status = (
        JobStatus.QUEUED if expected_status_code == 202 else JobStatus.FAILED
    )
    assert job.get_status() == expected_job_status


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_rerun_job_that_has_not_failed(
    app, add_battery_assets, clean_redis, requesting_user
):
    sensor = add_battery_assets["Test battery"].sensors[0]
    job = app.queues["scheduling"].enqueue(
        fail_on_purpose, meta=battery_schedule_meta(sensor)
    )

    with app.test_client() as client:
        response = client.post(url_for("JobAPI:rerun_job", uuid=job.id))

    assert response.status_code == 409
    assert "has not failed" in response.json["message"]
    assert app.queues["scheduling"].job_ids == [job.id], "the job is not queued twice"


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_rerun_job_without_asset_or_sensor(
    app, add_battery_assets, clean_redis, requesting_user
):
    job = failed_job(app.queues["forecasting"], {})

    with app.test_client() as client:
        response = client.post(url_for("JobAPI:rerun_job", uuid=job.id))

    assert response.status_code == 422
    assert "names no sensor" in response.json["message"]
    assert job.get_status() == JobStatus.FAILED


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_rerun_unknown_job(app, add_battery_assets, clean_redis, requesting_user):
    with app.test_client() as client:
        response = client.post(url_for("JobAPI:rerun_job", uuid="non-existent-uuid"))
    assert response.status_code == 404


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        ("test_prosumer_user@seita.nl", 202),
        # May read the asset and its sensors, but not trigger reports on it.
        ("test_admin_reader_user@seita.nl", 403),
    ],
    indirect=["requesting_user"],
)
def test_rerun_failed_report(
    app,
    setup_report_sensors,
    clean_redis,
    requesting_user,
    expected_status_code,
    monkeypatch,
):
    sensors = setup_report_sensors
    # Queue the report directly, as the report trigger endpoint does, so that each requesting user finds the same job.
    message = report_message(sensors["input_1"], sensors["input_2"], sensors["output"])
    reporter = get_data_generator(
        source=None,
        model=message["reporter"],
        config=message["config"],
        save_config=True,
        data_generator_type=Reporter,
    )
    queued = reporter.compute(as_job=True, parameters=message["parameters"])
    job = Job.fetch(queued["job_id"], connection=app.queues["reporting"].connection)

    def fail_report(**kwargs):
        raise ValueError("The report failed.")

    monkeypatch.setattr(
        "flexmeasures.data.services.reporting.run_report_job", fail_report
    )
    work_on_rq(app.queues["reporting"], max_jobs=1)
    assert job.get_status() == JobStatus.FAILED

    with app.test_client() as client:
        response = client.post(url_for("JobAPI:rerun_job", uuid=job.id))

    assert response.status_code == expected_status_code
    expected_job_status = (
        JobStatus.QUEUED if expected_status_code == 202 else JobStatus.FAILED
    )
    assert job.get_status() == expected_job_status


@pytest.mark.parametrize(
    "requesting_user, may_rerun",
    [
        ("test_prosumer_user@seita.nl", True),
        ("test_admin_reader_user@seita.nl", False),
    ],
    indirect=["requesting_user"],
)
def test_job_list_offers_rerun_of_failed_jobs_only(
    app, add_battery_assets, clean_redis, requesting_user, may_rerun
):
    battery = add_battery_assets["Test battery"]
    sensor = battery.sensors[0]
    failed = failed_job(app.queues["scheduling"], battery_schedule_meta(sensor))
    queued = app.queues["scheduling"].enqueue(
        fail_on_purpose, meta=battery_schedule_meta(sensor)
    )
    for job in (failed, queued):
        app.job_map.add(sensor.id, job.id, "scheduling", "sensor")

    def can_rerun_by_job_id(client) -> dict[str, bool]:
        response = client.get(
            url_for("AssetAPI:get_jobs", id=battery.id),
            query_string={"page": 1, "queue": "scheduling"},
        )
        assert response.status_code == 200
        return {job["job_id"]: job["can_rerun"] for job in response.json["jobs"]}

    with app.test_client() as client:
        assert can_rerun_by_job_id(client) == {
            failed.id: may_rerun,
            queued.id: False,
        }, "only a failed job can be re-run, and only by a user who may trigger it"
        if may_rerun:
            assert (
                client.post(url_for("JobAPI:rerun_job", uuid=failed.id)).status_code
                == 202
            )
            assert can_rerun_by_job_id(client) == {
                failed.id: False,
                queued.id: False,
            }, "a job that is queued again can no longer be re-run"


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        ("test_prosumer_user@seita.nl", 202),
        # May read the sensor, but not record data on it.
        ("test_admin_reader_user@seita.nl", 403),
        # May not even read the sensor.
        ("test_dummy_user_3@seita.nl", 403),
    ],
    indirect=["requesting_user"],
)
def test_rerun_failed_upload(
    app, add_battery_assets, clean_redis, requesting_user, expected_status_code
):
    sensor = add_battery_assets["Test battery"].sensors[0]
    # Sensor data uploads name their sensor in the job metadata.
    job = failed_job(app.queues["ingestion"], {"sensor_id": sensor.id})

    with app.test_client() as client:
        response = client.post(url_for("JobAPI:rerun_job", uuid=job.id))

    assert response.status_code == expected_status_code
    expected_job_status = (
        JobStatus.QUEUED if expected_status_code == 202 else JobStatus.FAILED
    )
    assert job.get_status() == expected_job_status


def failed_plugin_automation_job(app, db, asset, queue_name: str) -> Job:
    """Have a worker fail a job of an automation defined by a plugin, on the given queue."""
    automation = Automation(
        asset=asset,
        # The database outlives each test in this module, so each generator gets a name of its own.
        generator=DataSource(
            name=f"re-run test plugin generator {uuid4()}", type="ingester"
        ),
        name="Plugin automation to re-run",
        type="mock-ingestion",
        cronstr="0 6 * * *",
        parameters={},
    )
    db.session.add(automation)
    db.session.flush()
    queue = app.queues[queue_name]
    # The data source does not exist, so the job fails.
    job = queue.enqueue(
        execute_automation_job,
        automation_id=automation.id,
        data_source_id=-1,
        parameters={},
        meta={"asset_or_sensor": {"class": "Asset", "id": asset.id}},
    )
    work_on_rq(queue, max_jobs=1)
    assert (
        job.get_status() == JobStatus.FAILED
    ), "the job should fail for the test to mean anything"
    return job


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        ("test_prosumer_user@seita.nl", 202),
        # May read the asset, but not manage its automations.
        ("test_admin_reader_user@seita.nl", 403),
    ],
    indirect=["requesting_user"],
)
# A plugin chooses the queue of its automation jobs, and the permission does not depend on it.
@pytest.mark.parametrize("queue_name", ["ingestion", "reporting"])
def test_rerun_failed_plugin_automation_job(
    app,
    db,
    add_battery_assets,
    clean_redis,
    requesting_user,
    expected_status_code,
    queue_name,
):
    battery = add_battery_assets["Test battery"]
    job = failed_plugin_automation_job(app, db, battery, queue_name)

    with app.test_client() as client:
        response = client.post(url_for("JobAPI:rerun_job", uuid=job.id))

    assert response.status_code == expected_status_code, response.json
    expected_job_status = (
        JobStatus.QUEUED if expected_status_code == 202 else JobStatus.FAILED
    )
    assert job.get_status() == expected_job_status
