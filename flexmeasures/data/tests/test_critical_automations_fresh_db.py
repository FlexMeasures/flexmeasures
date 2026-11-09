"""Tests for flagging automations as critical, and the hooks their failures reach."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.automations import (
    Automation,
    AutomationRun,
    AutomationRunJob,
)
from flexmeasures.data.services.automation_failure_hooks import (
    get_automation_failure_hooks,
    register_automation_failure_hook,
)
from flexmeasures.data.services.automations import (
    AUTOMATION_RUN_MAX_DISPATCH_ATTEMPTS,
    mark_automation_run_dispatch_failed,
    record_automation_job_failed,
    update_automation,
)


@pytest.fixture()
def collected_pages(app):
    """Register a hook that collects what it is told, and take it off again afterwards."""
    pages = []
    register_automation_failure_hook(app, pages.append)
    yield pages
    app.automation_failure_hooks.remove(pages.append)


@pytest.fixture()
def forecast_automation(app, fresh_db, setup_fresh_test_forecast_data):
    """A forecast automation, not critical to begin with."""
    from flexmeasures.cli.data_add import add_automation

    sensor = setup_fresh_test_forecast_data["solar-sensor"]
    result = app.test_cli_runner().invoke(
        add_automation,
        to_flags(
            {
                "asset": sensor.generic_asset_id,
                "name": "Critical forecasts",
                "cron": "0 1 * * *",
                "timezone": "UTC",
                "sensor": sensor.id,
                "duration": "PT2H",
            }
        ),
    )
    assert result.exit_code == 0, result.output
    return fresh_db.session.scalars(select(Automation)).one()


def failed_run(db, automation: Automation, execution_state: str = "running"):
    """Persist a run of this automation with one job still going."""
    run = AutomationRun(
        automation=automation,
        scheduled_at=datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc),
        schedule_revision=automation.schedule_revision,
        automation_type=automation.type,
        dispatch_state="queued",
        execution_state=execution_state,
        attempt_count=1,
    )
    db.session.add(run)
    db.session.flush()
    db.session.add(
        AutomationRunJob(
            run=run,
            logical_job_key="cycle-001",
            rq_job_id=f"test-run-{run.id}-cycle-001",
            queue="forecasting",
            kind="forecast-cycle",
            status="running",
        )
    )
    db.session.commit()
    return run


def test_automations_are_not_critical_by_default(forecast_automation):
    assert forecast_automation.critical is False


def test_cli_creates_a_critical_automation(
    app, fresh_db, setup_fresh_test_forecast_data
):
    from flexmeasures.cli.data_add import add_automation

    sensor = setup_fresh_test_forecast_data["solar-sensor"]
    result = app.test_cli_runner().invoke(
        add_automation,
        to_flags(
            {
                "asset": sensor.generic_asset_id,
                "name": "Critical forecasts",
                "cron": "0 1 * * *",
                "timezone": "UTC",
                "sensor": sensor.id,
                "duration": "PT2H",
            }
        )
        + ["--critical"],
    )
    assert result.exit_code == 0, result.output
    assert "critical automation" in result.output
    assert fresh_db.session.scalars(select(Automation)).one().critical is True


def test_updating_criticality_does_not_disturb_the_recurrence(
    fresh_db, forecast_automation
):
    """Criticality says who is told about a failure, not which runs are due."""
    cursor_before = forecast_automation.cursor
    revision_before = forecast_automation.schedule_revision

    changes = update_automation(forecast_automation, critical=True, origin="test")

    assert changes == ["flagged as critical"]
    assert forecast_automation.critical is True
    assert forecast_automation.cursor == cursor_before
    assert forecast_automation.schedule_revision == revision_before


def test_a_failed_job_pages_for_a_critical_automation(
    fresh_db, forecast_automation, collected_pages
):
    forecast_automation.critical = True
    fresh_db.session.commit()
    run = failed_run(fresh_db, forecast_automation)

    record_automation_job_failed(
        run.id, "cycle-001", RuntimeError("the solver gave up")
    )

    assert len(collected_pages) == 1
    failure = collected_pages[0]
    assert failure.stage == "execution"
    assert failure.automation_id == forecast_automation.id
    assert failure.run_id == run.id
    assert failure.error_type == "RuntimeError"
    assert "the solver gave up" in failure.error_message
    assert "Critical automation" in failure.summary
    assert run.execution_state == "failed"
    assert run.critical_failure_notified_at is not None


def test_a_failed_job_pages_nobody_for_an_ordinary_automation(
    fresh_db, forecast_automation, collected_pages
):
    run = failed_run(fresh_db, forecast_automation)

    record_automation_job_failed(
        run.id, "cycle-001", RuntimeError("the solver gave up")
    )

    assert run.execution_state == "failed"
    assert collected_pages == []
    assert run.critical_failure_notified_at is None


def test_a_run_pages_once_however_many_of_its_jobs_fail(
    fresh_db, forecast_automation, collected_pages
):
    forecast_automation.critical = True
    fresh_db.session.commit()
    run = failed_run(fresh_db, forecast_automation)
    fresh_db.session.add(
        AutomationRunJob(
            run=run,
            logical_job_key="cycle-002",
            rq_job_id=f"test-run-{run.id}-cycle-002",
            queue="forecasting",
            kind="forecast-cycle",
            status="running",
        )
    )
    fresh_db.session.commit()

    record_automation_job_failed(run.id, "cycle-001", RuntimeError("first"))
    record_automation_job_failed(run.id, "cycle-002", RuntimeError("second"))

    assert len(collected_pages) == 1


def test_dispatch_pages_only_once_the_attempts_are_spent(
    fresh_db, forecast_automation, collected_pages
):
    """A dispatch the next retry would have fixed pages nobody."""
    forecast_automation.critical = True
    fresh_db.session.commit()
    run = failed_run(fresh_db, forecast_automation, execution_state="pending")

    run.attempt_count = 1
    fresh_db.session.commit()
    mark_automation_run_dispatch_failed(run.id, None, ValueError("Redis is away"))
    assert collected_pages == [], "a retryable dispatch failure must not page"

    run = fresh_db.session.get(AutomationRun, run.id)
    run.attempt_count = AUTOMATION_RUN_MAX_DISPATCH_ATTEMPTS
    fresh_db.session.commit()
    mark_automation_run_dispatch_failed(run.id, None, ValueError("Redis is still away"))

    assert len(collected_pages) == 1
    assert collected_pages[0].stage == "dispatch"
    assert collected_pages[0].error_type == "ValueError"


def test_a_hook_that_raises_does_not_break_the_record_of_the_failure(
    app, fresh_db, forecast_automation, collected_pages
):
    def unreachable_pager(failure):
        raise ConnectionError("the pager is down")

    register_automation_failure_hook(app, unreachable_pager)
    try:
        forecast_automation.critical = True
        fresh_db.session.commit()
        run = failed_run(fresh_db, forecast_automation)

        record_automation_job_failed(run.id, "cycle-001", RuntimeError("boom"))

        assert run.execution_state == "failed"
        assert run.last_error_message == "boom"
        assert len(collected_pages) == 1
    finally:
        app.automation_failure_hooks.remove(unreachable_pager)


def test_settings_can_name_a_hook_by_dotted_path(app):
    app.config["FLEXMEASURES_CRITICAL_AUTOMATION_FAILURE_HOOKS"] = [
        "flexmeasures.utils.time_utils.server_now"
    ]
    try:
        from flexmeasures.utils.time_utils import server_now

        assert server_now in get_automation_failure_hooks()
    finally:
        app.config["FLEXMEASURES_CRITICAL_AUTOMATION_FAILURE_HOOKS"] = []


def test_a_mistyped_hook_path_is_logged_and_skipped(app, caplog):
    app.config["FLEXMEASURES_CRITICAL_AUTOMATION_FAILURE_HOOKS"] = [
        "no.such.module.hook"
    ]
    try:
        assert get_automation_failure_hooks() == list(app.automation_failure_hooks)
        assert "Cannot use critical-automation-failure hook" in caplog.text
    finally:
        app.config["FLEXMEASURES_CRITICAL_AUTOMATION_FAILURE_HOOKS"] = []
