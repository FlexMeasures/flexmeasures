"""Tests for the automations endpoints (GET /api/v3_0/assets/<id>/automations[/<automation_id>])."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from flask import url_for

from flexmeasures.data.models.automations import (
    Automation,
    AutomationRun,
    AutomationRunAttempt,
    AutomationRunJob,
)
from flexmeasures.data.models.data_sources import DataSource


@pytest.fixture(scope="module")
def add_automations(db, add_battery_assets):
    battery = add_battery_assets["Test battery"]
    generator = DataSource(
        name="automations API test generator",
        type="forecaster",
        model="TrainPredictPipeline",
    )
    automations = [
        Automation(
            asset_id=battery.id,
            generator=generator,
            type="forecasts",
            name="Day-ahead forecasts",
            cronstr="0 6 * * *",
            timezone="Europe/Amsterdam",
            cursor=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
            active=True,
            parameters={"sensor": battery.sensors[0].id},
        ),
        Automation(
            asset_id=battery.id,
            generator=generator,
            type="forecasts",
            name="Intraday forecasts",
            cronstr="0 * * * *",
            timezone="UTC",
            cursor=datetime(2026, 7, 11, 5, 0, tzinfo=timezone.utc),
            active=False,
            parameters={"sensor": battery.sensors[0].id},
        ),
    ]
    db.session.add_all(automations)
    db.session.flush()
    run = AutomationRun(
        automation=automations[0],
        scheduled_at=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
        schedule_revision=automations[0].schedule_revision,
        automation_type="forecasts",
        generator_id=generator.id,
        dispatch_state="partially_queued",
        execution_state="pending",
        attempt_count=2,
        first_enqueued_at=datetime(2026, 7, 11, 4, 1, tzinfo=timezone.utc),
        parameters=dict(automations[0].parameters),
        plan={"cronstr": automations[0].cronstr, "timezone": automations[0].timezone},
        last_error_type="ConnectionError",
        last_error_message="lost Redis connection",
    )
    db.session.add(run)
    db.session.flush()
    db.session.add_all(
        [
            AutomationRunJob(
                run=run,
                logical_job_key="cycle-001",
                rq_job_id=f"automation-run-{run.id}-cycle-001",
                queue="forecasting",
                kind="forecast-cycle",
                status="queued",
                depends_on=[],
                payload={},
            ),
            AutomationRunJob(
                run=run,
                logical_job_key="wrap-up",
                rq_job_id=f"automation-run-{run.id}-wrap-up",
                queue="forecasting",
                kind="forecast-wrap-up",
                status="pending",
                depends_on=["cycle-001"],
                payload={},
            ),
        ]
    )
    # The second automation shows the other two outcomes an operator needs to tell apart:
    # an occurrence which failed before queueing anything, and one which queued and then ran to completion.
    failed_before_queueing = AutomationRun(
        automation=automations[1],
        scheduled_at=datetime(2026, 7, 11, 5, 0, tzinfo=timezone.utc),
        schedule_revision=automations[1].schedule_revision,
        automation_type="forecasts",
        generator_id=generator.id,
        dispatch_state="failed",
        execution_state="pending",
        attempt_count=1,
        parameters=dict(automations[1].parameters),
        plan={"cronstr": automations[1].cronstr, "timezone": automations[1].timezone},
        last_error_type="ValidationError",
        last_error_message="forecast output sensor no longer exists",
    )
    fully_queued_and_succeeded = AutomationRun(
        automation=automations[1],
        scheduled_at=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
        schedule_revision=automations[1].schedule_revision,
        automation_type="forecasts",
        generator_id=generator.id,
        dispatch_state="queued",
        execution_state="succeeded",
        attempt_count=2,
        first_enqueued_at=datetime(2026, 7, 11, 4, 1, tzinfo=timezone.utc),
        dispatch_completed_at=datetime(2026, 7, 11, 4, 2, tzinfo=timezone.utc),
        execution_started_at=datetime(2026, 7, 11, 4, 3, tzinfo=timezone.utc),
        execution_completed_at=datetime(2026, 7, 11, 4, 9, tzinfo=timezone.utc),
        parameters=dict(automations[1].parameters),
        plan={"cronstr": automations[1].cronstr, "timezone": automations[1].timezone},
    )
    db.session.add_all([failed_before_queueing, fully_queued_and_succeeded])
    db.session.flush()
    db.session.add_all(
        [
            AutomationRunAttempt(
                run=failed_before_queueing,
                attempt_no=1,
                owner="runner-a:1",
                started_at=datetime(2026, 7, 11, 5, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 7, 11, 5, 0, tzinfo=timezone.utc),
                outcome="failed",
                queued_job_count=0,
                error_type="ValidationError",
                error_message="forecast output sensor no longer exists",
            ),
            AutomationRunAttempt(
                run=fully_queued_and_succeeded,
                attempt_no=1,
                owner="runner-a:1",
                started_at=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
                outcome="failed",
                queued_job_count=0,
                error_type="ConnectionError",
                error_message="lost Redis connection",
            ),
            AutomationRunAttempt(
                run=fully_queued_and_succeeded,
                attempt_no=2,
                owner="runner-b:2",
                started_at=datetime(2026, 7, 11, 4, 1, tzinfo=timezone.utc),
                finished_at=datetime(2026, 7, 11, 4, 2, tzinfo=timezone.utc),
                outcome="queued",
                queued_job_count=1,
            ),
            AutomationRunJob(
                run=fully_queued_and_succeeded,
                logical_job_key="cycle-001",
                rq_job_id=f"automation-run-{fully_queued_and_succeeded.id}-cycle-001",
                queue="forecasting",
                kind="forecast-cycle",
                status="succeeded",
                depends_on=[],
                payload={},
                enqueued_at=datetime(2026, 7, 11, 4, 1, tzinfo=timezone.utc),
                started_at=datetime(2026, 7, 11, 4, 3, tzinfo=timezone.utc),
                finished_at=datetime(2026, 7, 11, 4, 9, tzinfo=timezone.utc),
            ),
        ]
    )
    return automations


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        (None, 401),  # not logged in
        ("test_prosumer_user@seita.nl", 200),  # same account
        ("test_dummy_user_3@seita.nl", 403),  # different account
    ],
    indirect=["requesting_user"],
)
def test_get_automations_auth(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
    expected_status_code,
):
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.get(
            url_for("AssetAPI:get_automations", id=battery.id),
        )
    assert response.status_code == expected_status_code


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automations(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.get(
            url_for("AssetAPI:get_automations", id=battery.id),
        )
    assert response.status_code == 200
    automations = response.json["automations"]
    assert len(automations) == 2
    day_ahead = next(a for a in automations if a["name"] == "Day-ahead forecasts")
    assert day_ahead["type"] == "forecasts"
    assert day_ahead["cronstr"] == "0 6 * * *"
    assert day_ahead["timezone"] == "Europe/Amsterdam"
    assert day_ahead["cursor"] == "2026-07-11T04:00:00+00:00"
    assert day_ahead["schedule_revision"] == 1
    assert day_ahead["recurrence_description"] == "At 06:00"
    assert day_ahead["active"] is True
    assert day_ahead["created_at"] is not None
    # generator and parameters are not listed
    assert "generator_id" not in day_ahead
    assert "generator" not in day_ahead
    assert "parameters" not in day_ahead


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automation_details(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    battery = add_battery_assets["Test battery"]
    automation = add_automations[0]
    with app.test_client() as client:
        response = client.get(
            url_for(
                "AssetAPI:get_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
        )
    assert response.status_code == 200
    assert response.json["name"] == "Day-ahead forecasts"
    assert response.json["timezone"] == "Europe/Amsterdam"
    assert response.json["cursor"] == "2026-07-11T04:00:00+00:00"
    assert response.json["schedule_revision"] == 1
    assert response.json["parameters"] == {"sensor": battery.sensors[0].id}
    assert response.json["job_stats"] == {}  # this automation has not queued any jobs
    run_stats = response.json["run_stats"]
    assert run_stats["total"] == 1
    assert run_stats["dispatch"] == {"partially_queued": 1}
    assert run_stats["execution"] == {"pending": 1}
    assert run_stats["latest_run"]["dispatch_state"] == "partially_queued"
    assert run_stats["latest_run"]["attempt_count"] == 2
    assert run_stats["latest_run"]["queued_job_count"] == 1
    assert run_stats["latest_run"]["last_error"] == {
        "type": "ConnectionError",
        "message": "lost Redis connection",
    }
    assert [job["logical_job_key"] for job in run_stats["latest_run"]["jobs"]] == [
        "cycle-001",
        "wrap-up",
    ]
    # the sensor to forecast is both read from (its history) and written to
    sensor = {"id": battery.sensors[0].id, "name": battery.sensors[0].name}
    assert response.json["input_sensors"] == [sensor]
    assert response.json["output_sensors"] == [sensor]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automation_details_distinguishes_run_outcomes(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    """An operator can tell a pre-queue failure, a completed dispatch and its execution outcome apart."""
    battery = add_battery_assets["Test battery"]
    automation = add_automations[1]
    with app.test_client() as client:
        response = client.get(
            url_for(
                "AssetAPI:get_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
        )
    assert response.status_code == 200
    run_stats = response.json["run_stats"]
    assert run_stats["total"] == 2
    assert run_stats["dispatch"] == {"failed": 1, "queued": 1}
    assert run_stats["execution"] == {"pending": 1, "succeeded": 1}

    # The most recent occurrence failed before it queued anything, so it can be retried in full.
    latest_run = run_stats["latest_run"]
    assert latest_run["scheduled_at"] == "2026-07-11T05:00:00+00:00"
    assert latest_run["dispatch_state"] == "failed"
    assert latest_run["intended_job_count"] == 0
    assert latest_run["queued_job_count"] == 0
    assert latest_run["first_enqueued_at"] is None
    assert latest_run["last_error"] == {
        "type": "ValidationError",
        "message": "forecast output sensor no longer exists",
    }
    assert latest_run["latest_attempt"]["attempt_no"] == 1
    assert latest_run["latest_attempt"]["outcome"] == "failed"

    # The earlier occurrence needed a retry, finished queueing, and its jobs then succeeded.
    retried_run = run_stats["recent_runs"][1]
    assert retried_run["scheduled_at"] == "2026-07-11T04:00:00+00:00"
    assert retried_run["dispatch_state"] == "queued"
    assert retried_run["execution_state"] == "succeeded"
    assert retried_run["attempt_count"] == 2
    assert retried_run["dispatch_completed_at"] == "2026-07-11T04:02:00+00:00"
    assert retried_run["execution_completed_at"] == "2026-07-11T04:09:00+00:00"
    assert retried_run["latest_attempt"]["attempt_no"] == 2
    assert retried_run["latest_attempt"]["owner"] == "runner-b:2"
    assert retried_run["latest_attempt"]["outcome"] == "queued"
    assert retried_run["latest_attempt"]["error"] is None
    assert [job["status"] for job in retried_run["jobs"]] == ["succeeded"]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automation_of_other_asset(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    """Requesting an automation via an asset it does not belong to should return 404."""
    other_asset = add_battery_assets["Test small battery"]
    automation = add_automations[0]
    with app.test_client() as client:
        response = client.get(
            url_for(
                "AssetAPI:get_automation",
                id=other_asset.id,
                automation_id=automation.id,
            ),
        )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_nonexistent_automation(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.get(
            url_for("AssetAPI:get_automation", id=battery.id, automation_id=9999),
        )
    assert response.status_code == 404
