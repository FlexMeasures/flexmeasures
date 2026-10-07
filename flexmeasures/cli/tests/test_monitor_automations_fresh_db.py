"""Tests for `flexmeasures monitor automations`, which emails a digest of failed automation runs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.automations import Automation, AutomationRun

RECIPIENT = "ops@example.test"
DUE_AT = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="function")
def clean_redis(app):
    app.redis_connection.flushdb()
    yield
    app.redis_connection.flushdb()


@pytest.fixture()
def forecast_automation(
    app, fresh_db, clean_redis, setup_fresh_test_forecast_data, freeze_server_now
):
    """Create a forecast automation which is due at the frozen minute."""
    from flexmeasures.cli.data_add import add_automation

    freeze_server_now(DUE_AT - timedelta(minutes=2))
    sensor = setup_fresh_test_forecast_data["solar-sensor"]
    result = app.test_cli_runner().invoke(
        add_automation,
        to_flags(
            {
                "asset": sensor.generic_asset_id,
                "name": "Monitored forecasts",
                "cron": "0 1 * * *",
                "timezone": "UTC",
                "sensor": sensor.id,
                "duration": "PT2H",
                "forecast-frequency": "PT1H",
                "max-forecast-horizon": "PT2H",
                "retrain-frequency": "PT1H",
            }
        ),
    )
    assert result.exit_code == 0, result.output
    freeze_server_now(DUE_AT)
    return fresh_db.session.scalars(select(Automation)).one()


def run_automations(app, exit_code: int = 0):
    from flexmeasures.cli.jobs import run_automations as run_automations_command

    result = app.test_cli_runner().invoke(run_automations_command)
    assert result.exit_code == exit_code, result.output


def monitor(app, *args: str):
    """Run the monitor, returning its result and the emails it sent."""
    from flexmeasures.cli.monitor import monitor_automations

    with app.mail.record_messages() as outbox:
        result = app.test_cli_runner().invoke(
            monitor_automations, ["--recipient", RECIPIENT, *args]
        )
    return result, outbox


def perform_job(app, intent):
    from rq import SimpleWorker

    queue = app.queues["forecasting"]
    worker = SimpleWorker([queue], connection=queue.connection)
    worker.perform_job(queue.fetch_job(intent.rq_job_id), queue)


def add_run(
    db, automation: Automation, scheduled_at: datetime, **columns
) -> AutomationRun:
    """Record a run of the automation in whatever state the test needs, dispatched by default."""
    columns = {
        "automation_type": automation.type,
        "dispatch_state": "queued",
        "dispatch_completed_at": scheduled_at,
        "execution_state": "pending",
        "attempt_count": 1,
        **columns,
    }
    run = AutomationRun(
        automation=automation,
        scheduled_at=scheduled_at,
        schedule_revision=automation.schedule_revision,
        generator_id=automation.generator_id,
        parameters={},
        plan={},
        **columns,
    )
    db.session.add(run)
    db.session.commit()
    return run


def test_a_failed_forecast_is_reported_once(app, fresh_db, forecast_automation):
    """A forecast run whose job failed on the worker is emailed about, and only the first time the monitor runs."""
    run_automations(app)
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    queue = app.queues["forecasting"]
    wrap_up = next(i for i in run.job_intents if i.kind == "forecast-wrap-up")
    cycle = next(i for i in run.job_intents if i.kind == "forecast-cycle")
    # Make the wrap-up job fail by taking away one of the cycle jobs it reports on.
    queue.fetch_job(cycle.rq_job_id).delete()
    perform_job(app, wrap_up)
    fresh_db.session.refresh(run)
    assert run.execution_state == "failed"

    result, outbox = monitor(app)

    assert result.exit_code == 0, result.output
    assert len(outbox) == 1
    assert outbox[0].bcc == [RECIPIENT]
    assert outbox[0].subject == "Failed runs of 1 automation(s)"
    body = outbox[0].body
    assert (
        f"Automation {forecast_automation.id} 'Monitored forecasts' (forecasting)"
        in body
    )
    assert "failed once (execution failed: 1), last at 2026-08-05 01:00 UTC" in body
    assert f"last error: {run.last_error_type}" in body
    fresh_db.session.refresh(run)
    assert run.alerted_at == DUE_AT

    result, outbox = monitor(app)

    assert result.exit_code == 0, result.output
    assert outbox == []
    assert "All good" in result.output


def test_a_running_forecast_is_reported_once_it_is_stuck(
    app, fresh_db, forecast_automation, freeze_server_now
):
    """A forecast run which started executing is reported once it has been at it for longer than the configured threshold."""
    run_automations(app)
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    # The wrap-up job succeeds while the cycle jobs have not run, so the run keeps executing.
    perform_job(app, next(i for i in run.job_intents if i.kind == "forecast-wrap-up"))
    fresh_db.session.refresh(run)
    assert run.execution_state == "running"

    freeze_server_now(DUE_AT + timedelta(hours=5, minutes=59))
    result, outbox = monitor(app)
    assert result.exit_code == 0, result.output
    assert outbox == []

    freeze_server_now(DUE_AT + timedelta(hours=6))
    result, outbox = monitor(app)
    assert result.exit_code == 0, result.output
    assert len(outbox) == 1
    assert "failed once (stuck: 1)" in outbox[0].body
    assert "last error" not in outbox[0].body


def test_the_stuck_threshold_comes_from_the_config_or_the_command_line(
    app, fresh_db, forecast_automation, freeze_server_now, monkeypatch
):
    """The command-line option overrides the configured threshold, which overrides the default of six hours."""
    stuck_since = DUE_AT - timedelta(hours=2)
    add_run(
        fresh_db,
        forecast_automation,
        stuck_since,
        execution_state="running",
        execution_started_at=stuck_since,
    )

    result, outbox = monitor(app, "--stuck-after-minutes", "180")
    assert result.exit_code == 0, result.output
    assert outbox == []

    monkeypatch.setitem(
        app.config, "FLEXMEASURES_MONITOR_AUTOMATIONS_STUCK_AFTER", timedelta(hours=1)
    )
    result, outbox = monitor(app, "--stuck-after-minutes", "180")
    assert result.exit_code == 0, result.output
    assert outbox == []

    result, outbox = monitor(app)
    assert result.exit_code == 0, result.output
    assert len(outbox) == 1
    assert "longer than 1 hour" in outbox[0].body


def test_a_forecast_dispatch_is_reported_once_its_attempts_are_used_up(
    app, fresh_db, forecast_automation, freeze_server_now, mocker
):
    """A forecast run whose dispatch failed is retried, so it is only reported once it will not be tried again."""
    from flexmeasures.data.services.automations import (
        AUTOMATION_RUN_MAX_DISPATCH_ATTEMPTS,
    )

    mocker.patch.object(
        app.queues["forecasting"],
        "enqueue_job",
        side_effect=RuntimeError("redis unavailable"),
    )
    run_automations(app, exit_code=1)
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    assert run.dispatch_state == "failed"

    result, outbox = monitor(app)
    assert result.exit_code == 0, result.output
    assert outbox == []

    # Each attempt waits longer than the last, so stepping an hour ahead each time takes them all.
    for attempt_no in range(2, AUTOMATION_RUN_MAX_DISPATCH_ATTEMPTS + 1):
        freeze_server_now(DUE_AT + timedelta(hours=attempt_no))
        result, outbox = monitor(app)
        assert outbox == [], f"reported before attempt {attempt_no}"
        run_automations(app, exit_code=1)
    fresh_db.session.refresh(run)
    assert run.attempt_count == AUTOMATION_RUN_MAX_DISPATCH_ATTEMPTS

    result, outbox = monitor(app)
    assert result.exit_code == 0, result.output
    assert len(outbox) == 1
    assert "failed once (dispatch failed: 1)" in outbox[0].body
    assert "last error: RuntimeError: redis unavailable" in outbox[0].body


def test_which_runs_count_as_failed(fresh_db, forecast_automation):
    """Failures are judged the same way for every automation type, except that only a forecast run is dispatched again."""
    from flexmeasures.data.services.automation_monitoring import (
        get_unalerted_failed_automation_runs,
    )

    def add(minute: int, **columns) -> AutomationRun:
        return add_run(
            fresh_db, forecast_automation, DUE_AT - timedelta(minutes=minute), **columns
        )

    expected = {
        add(1, execution_state="failed").id: "execution failed",
        add(
            2,
            execution_state="running",
            execution_started_at=DUE_AT - timedelta(hours=7),
        ).id: "stuck",
        # A schedule run is never dispatched again, so its first failed attempt is its last.
        add(
            3,
            automation_type="scheduling",
            dispatch_state="failed",
            dispatch_completed_at=None,
            claim_expires_at=DUE_AT + timedelta(minutes=1),
        ).id: "dispatch failed",
        # A runner which died mid-dispatch leaves its claim behind, until its lease runs out.
        add(
            4,
            automation_type="reporting",
            dispatch_state="claimed",
            dispatch_completed_at=None,
            claim_owner="runner:dead",
            claim_expires_at=DUE_AT - timedelta(minutes=1),
        ).id: "dispatch failed",
    }
    not_failed = [
        add(5, execution_state="succeeded"),
        add(
            6,
            execution_state="running",
            execution_started_at=DUE_AT - timedelta(hours=5),
        ),
        # A forecast run with attempts to spare will be dispatched again.
        add(7, dispatch_state="failed", dispatch_completed_at=None),
        # A runner is still dispatching this one.
        add(
            8,
            automation_type="scheduling",
            dispatch_state="claimed",
            dispatch_completed_at=None,
            claim_owner="runner:alive",
            claim_expires_at=DUE_AT + timedelta(minutes=5),
        ),
        add(9, execution_state="failed", alerted_at=DUE_AT - timedelta(hours=1)),
    ]

    failed_runs = get_unalerted_failed_automation_runs(timedelta(hours=6), now=DUE_AT)

    assert {f.run.id: f.reason for f in failed_runs} == expected
    assert not {run.id for run in not_failed} & {f.run.id for f in failed_runs}


def test_repeated_failures_are_collapsed_per_automation(
    app, fresh_db, forecast_automation
):
    """An automation which failed several times takes up one entry, naming its latest failure and error."""
    for hours_ago, error in ((3, "first"), (1, "latest"), (2, "middle")):
        add_run(
            fresh_db,
            forecast_automation,
            DUE_AT - timedelta(hours=hours_ago),
            execution_state="failed",
            last_error_type="ValueError",
            last_error_message=error,
        )
    add_run(
        fresh_db,
        forecast_automation,
        DUE_AT - timedelta(minutes=30),
        automation_type="scheduling",
        dispatch_state="failed",
        dispatch_completed_at=None,
    )

    result, outbox = monitor(app)

    assert result.exit_code == 0, result.output
    assert len(outbox) == 1
    body = outbox[0].body
    assert body.count(f"Automation {forecast_automation.id} ") == 1
    assert (
        "failed 4 times (execution failed: 3, dispatch failed: 1), last at 2026-08-05 00:30 UTC"
        in body
    )
    # The dispatch failure recorded no error, so the latest error is that of the latest failed execution.
    assert "last error: ValueError: latest" in body
    assert all(
        run.alerted_at is not None
        for run in fresh_db.session.scalars(select(AutomationRun))
    )


def test_without_recipients_nothing_is_marked_as_reported(
    app, fresh_db, forecast_automation, monkeypatch
):
    """Without anyone to email, the monitor refuses to run, rather than marking runs as reported that nobody heard of."""
    from flexmeasures.cli.monitor import monitor_automations

    monkeypatch.setitem(
        app.config, "FLEXMEASURES_DEFAULT_MONITORING_MAIL_RECIPIENTS", []
    )
    monkeypatch.setitem(app.config, "FLEXMEASURES_MONITORING_MAIL_RECIPIENTS", [])
    run = add_run(fresh_db, forecast_automation, DUE_AT, execution_state="failed")

    result = app.test_cli_runner().invoke(monitor_automations)

    assert result.exit_code == 2
    assert "Nobody to send the digest to" in result.output
    fresh_db.session.refresh(run)
    assert run.alerted_at is None
