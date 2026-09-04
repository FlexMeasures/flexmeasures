"""Regression tests for durable automation run dispatch."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError, IntegrityError

from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.automations import (
    Automation,
    AutomationRun,
    AutomationRunJob,
)


@pytest.fixture(scope="function")
def clean_redis(app):
    app.redis_connection.flushdb()
    yield
    app.redis_connection.flushdb()


@pytest.fixture()
def due_forecast_automation(
    app, fresh_db, setup_fresh_test_forecast_data, freeze_server_now
):
    """Create a persisted forecast automation due at the frozen minute."""
    from flexmeasures.cli.data_add import add_automation

    freeze_server_now(datetime(2026, 8, 5, 0, 58, tzinfo=timezone.utc))
    sensor = setup_fresh_test_forecast_data["solar-sensor"]
    runner = app.test_cli_runner()
    result = runner.invoke(
        add_automation,
        to_flags(
            {
                "asset": sensor.generic_asset_id,
                "name": "Durable forecasts",
                "cron": "0 1 * * *",
                "timezone": "UTC",
                "sensor": sensor.id,
                "start": "2026-08-05T01:00:00+00:00",
                "duration": "PT2H",
                "forecast-frequency": "PT1H",
                "max-forecast-horizon": "PT2H",
                "retrain-frequency": "PT1H",
            }
        ),
    )
    assert result.exit_code == 0, result.output
    automation = fresh_db.session.scalars(select(Automation)).one()
    freeze_server_now(datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc))
    return automation


def test_automation_run_unique_per_revision(fresh_db, due_forecast_automation):
    """A scheduled occurrence is unique for one automation revision."""
    scheduled_at = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
    run = AutomationRun(
        automation=due_forecast_automation,
        scheduled_at=scheduled_at,
        schedule_revision=due_forecast_automation.schedule_revision,
        automation_type="forecasts",
        generator_id=due_forecast_automation.generator_id,
        dispatch_state="pending",
        execution_state="pending",
        parameters=dict(due_forecast_automation.parameters),
        plan={},
    )
    fresh_db.session.add(run)
    fresh_db.session.commit()

    duplicate = AutomationRun(
        automation=due_forecast_automation,
        scheduled_at=scheduled_at,
        schedule_revision=due_forecast_automation.schedule_revision,
        automation_type="forecasts",
        generator_id=due_forecast_automation.generator_id,
        dispatch_state="pending",
        execution_state="pending",
        parameters=dict(due_forecast_automation.parameters),
        plan={},
    )
    fresh_db.session.add(duplicate)

    with pytest.raises(IntegrityError):
        fresh_db.session.commit()
    fresh_db.session.rollback()

    same_occurrence_new_revision = AutomationRun(
        automation=due_forecast_automation,
        scheduled_at=scheduled_at,
        schedule_revision=due_forecast_automation.schedule_revision + 1,
        automation_type="forecasts",
        generator_id=due_forecast_automation.generator_id,
        dispatch_state="pending",
        execution_state="pending",
        parameters=dict(due_forecast_automation.parameters),
        plan={},
    )
    fresh_db.session.add(same_occurrence_new_revision)
    fresh_db.session.commit()


def test_job_intents_are_unique_per_run(fresh_db, due_forecast_automation):
    """The database rejects duplicate logical job keys for one run."""
    run = AutomationRun(
        automation=due_forecast_automation,
        scheduled_at=datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc),
        schedule_revision=due_forecast_automation.schedule_revision,
        automation_type="forecasts",
        generator_id=due_forecast_automation.generator_id,
        dispatch_state="pending",
        execution_state="pending",
        parameters=dict(due_forecast_automation.parameters),
        plan={},
    )
    fresh_db.session.add(run)
    fresh_db.session.flush()
    fresh_db.session.add_all(
        [
            AutomationRunJob(
                run=run,
                logical_job_key="cycle-001",
                rq_job_id="automation-run-test-cycle-001",
                queue="forecasting",
                kind="forecast-cycle",
                status="pending",
                depends_on=[],
                payload={},
            ),
            AutomationRunJob(
                run=run,
                logical_job_key="cycle-001",
                rq_job_id="automation-run-test-cycle-duplicate",
                queue="forecasting",
                kind="forecast-cycle",
                status="pending",
                depends_on=[],
                payload={},
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        fresh_db.session.commit()


def test_failed_before_first_enqueue_can_be_retried(
    app, fresh_db, clean_redis, due_forecast_automation, mocker
):
    """A pre-enqueue failure leaves no Redis job and a retryable durable run."""
    from flexmeasures.cli.jobs import run_automations

    queue = app.queues["forecasting"]
    original_enqueue_job = queue.enqueue_job
    patched_enqueue_job = mocker.patch.object(
        queue, "enqueue_job", side_effect=RuntimeError("redis unavailable")
    )
    runner = app.test_cli_runner()

    first_result = runner.invoke(run_automations)

    assert first_result.exit_code == 1, first_result.output
    assert queue.count == 0
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    assert run.dispatch_state == "failed"
    assert run.queued_job_count == 0
    assert run.attempt_count == 1

    patched_enqueue_job.side_effect = lambda job: original_enqueue_job(job)
    retry_result = runner.invoke(run_automations)

    assert retry_result.exit_code == 0, retry_result.output
    fresh_db.session.refresh(run)
    assert run.dispatch_state == "queued"
    assert run.attempt_count == 2
    assert run.queued_job_count == run.intended_job_count
    assert queue.count > 0


def test_partial_enqueue_retry_queues_only_missing_jobs(
    app, fresh_db, clean_redis, due_forecast_automation, mocker
):
    """A partial dispatch retry keeps queued job IDs and only enqueues missing intents."""
    from flexmeasures.cli.jobs import run_automations

    queue = app.queues["forecasting"]
    original_enqueue_job = queue.enqueue_job
    calls = []

    def enqueue_once_then_fail(job):
        calls.append(job.id)
        if len(calls) == 1:
            return original_enqueue_job(job)
        raise RuntimeError("lost connection after first job")

    patched_enqueue_job = mocker.patch.object(
        queue, "enqueue_job", side_effect=enqueue_once_then_fail
    )
    runner = app.test_cli_runner()

    first_result = runner.invoke(run_automations)

    assert first_result.exit_code == 1, first_result.output
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    first_job_ids = [intent.rq_job_id for intent in run.job_intents]
    assert run.dispatch_state == "partially_queued"
    assert run.queued_job_count == 1

    patched_enqueue_job.side_effect = lambda job: original_enqueue_job(job)
    retry_result = runner.invoke(run_automations)

    assert retry_result.exit_code == 0, retry_result.output
    fresh_db.session.refresh(run)
    assert [intent.rq_job_id for intent in run.job_intents] == first_job_ids
    assert run.dispatch_state == "queued"
    assert run.queued_job_count == run.intended_job_count
    assert queue.fetch_job(first_job_ids[0]) is not None


def test_stale_claim_is_adopted_after_restart(
    fresh_db, due_forecast_automation, freeze_server_now
):
    """A stale SQL claim is reused by a later runner without creating a new run."""
    from flexmeasures.data.services.automations import (
        claim_existing_automation_run,
        get_due_automations,
        claim_due_automation_run,
    )

    due = get_due_automations(datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc))[0]
    claimed = claim_due_automation_run(due, owner="first-runner")
    assert claimed is not None
    run_id = claimed.run.id

    claimed.run.claim_expires_at = datetime(2026, 8, 5, 1, 4, tzinfo=timezone.utc)
    fresh_db.session.commit()
    freeze_server_now(datetime(2026, 8, 5, 1, 5, tzinfo=timezone.utc))
    fresh_db.session.remove()

    run = fresh_db.session.get(AutomationRun, run_id)
    adopted = claim_existing_automation_run(run, owner="second-runner")

    assert adopted is not None
    assert adopted.run.id == run_id
    assert adopted.run.claim_owner == "second-runner"
    assert adopted.run.attempt_count == 2


def test_fresh_claim_blocks_second_runner(fresh_db, due_forecast_automation):
    """A non-stale SQL claim cannot be adopted by another runner."""
    from flexmeasures.data.services.automations import (
        claim_existing_automation_run,
        get_due_automations,
        claim_due_automation_run,
    )

    due = get_due_automations(datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc))[0]
    claimed = claim_due_automation_run(due, owner="first-runner")
    assert claimed is not None

    adopted = claim_existing_automation_run(claimed.run, owner="second-runner")

    assert adopted is None
    fresh_db.session.refresh(claimed.run)
    assert claimed.run.claim_owner == "first-runner"


def test_run_plan_snapshot_is_immutable_after_automation_edit(
    app, fresh_db, clean_redis, due_forecast_automation
):
    """Retries use the original run parameters even after automation edits."""
    from flexmeasures.cli.jobs import run_automations

    runner = app.test_cli_runner()
    first_result = runner.invoke(run_automations)
    assert first_result.exit_code == 0, first_result.output
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    original_parameters = dict(run.parameters)
    original_revision = run.schedule_revision

    due_forecast_automation.parameters["duration"] = "PT4H"
    due_forecast_automation.cronstr = "30 1 * * *"
    due_forecast_automation.schedule_revision += 1
    fresh_db.session.commit()
    fresh_db.session.refresh(run)

    assert run.parameters == original_parameters
    assert run.schedule_revision == original_revision
    assert run.plan["cronstr"] == "0 1 * * *"


def test_live_partial_dispatch_claim_is_not_stolen(fresh_db, due_forecast_automation):
    """A runner which is still queueing keeps its claim, even while partially queued.

    The dispatch state turns to 'partially_queued' as soon as the first job is queued, so a second runner
    must fall back on the claim lease to decide whether the first runner is gone.
    """
    from flexmeasures.data.services.automations import (
        claim_due_automation_run,
        claim_existing_automation_run,
        get_due_automations,
    )

    due = get_due_automations(datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc))[0]
    claimed = claim_due_automation_run(due, owner="first-runner")
    assert claimed is not None
    # The first runner queued one of its jobs and is still working on the rest.
    claimed.run.dispatch_state = "partially_queued"
    fresh_db.session.commit()

    adopted = claim_existing_automation_run(claimed.run, owner="second-runner")

    assert adopted is None
    fresh_db.session.refresh(claimed.run)
    assert claimed.run.claim_owner == "first-runner"
    assert claimed.run.attempt_count == 1


def test_crash_between_last_enqueue_and_dispatch_completion_is_finalized(
    app, fresh_db, clean_redis, due_forecast_automation, mocker, freeze_server_now
):
    """A crash after the last enqueue, but before dispatch is marked complete, still gets finalized.

    All jobs are already in Redis, so a later runner must adopt the abandoned claim, reconcile the durable
    intents against Redis, and complete the dispatch without queueing anything again.
    """
    from flexmeasures.cli.jobs import run_automations
    from flexmeasures.data.services import automations as automations_service

    real_mark_queued = automations_service.mark_automation_run_dispatch_queued
    marks: list[int] = []

    def crash_on_first_completion(run_id, attempt=None):
        marks.append(run_id)
        if len(marks) == 1:
            raise RuntimeError("died before recording dispatch completion")
        return real_mark_queued(run_id, attempt)

    mocker.patch(
        "flexmeasures.data.services.automations.mark_automation_run_dispatch_queued",
        side_effect=crash_on_first_completion,
    )
    runner = app.test_cli_runner()

    first_result = runner.invoke(run_automations)

    assert first_result.exit_code == 1, first_result.output
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    queued_job_ids = [intent.rq_job_id for intent in run.job_intents]
    assert run.queued_job_count == run.intended_job_count
    assert run.dispatch_completed_at is None
    queue = app.queues["forecasting"]
    jobs_after_crash = queue.count

    # The abandoned claim only becomes adoptable once its lease has expired.
    freeze_server_now(datetime(2026, 8, 5, 1, 30, tzinfo=timezone.utc))
    fresh_db.session.remove()

    retry_result = runner.invoke(run_automations)

    assert retry_result.exit_code == 0, retry_result.output
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    assert run.dispatch_state == "queued"
    assert run.dispatch_completed_at is not None
    assert run.claim_owner is None
    # Reconciliation recognised the existing Redis jobs, so nothing was queued twice.
    assert [intent.rq_job_id for intent in run.job_intents] == queued_job_ids
    assert queue.count == jobs_after_crash


def test_death_after_claim_is_recovered_once_the_lease_expires(
    app, fresh_db, clean_redis, due_forecast_automation, freeze_server_now
):
    """A runner which dies right after claiming an occurrence queues nothing and blocks nothing.

    The occurrence stays claimed until the lease runs out, after which a later runner adopts the same durable run
    instead of creating a second one.
    """
    from flexmeasures.cli.jobs import run_automations
    from flexmeasures.data.services.automations import (
        claim_due_automation_run,
        get_due_automations,
    )

    due = get_due_automations(datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc))[0]
    claimed = claim_due_automation_run(due, owner="runner-that-dies")
    assert claimed is not None
    run_id = claimed.run.id
    queue = app.queues["forecasting"]
    assert claimed.run.job_intents == []
    assert queue.count == 0

    # While the lease is live, nothing else touches the occurrence.
    runner = app.test_cli_runner()
    blocked_result = runner.invoke(run_automations)
    assert blocked_result.exit_code == 0, blocked_result.output
    assert queue.count == 0

    freeze_server_now(datetime(2026, 8, 5, 1, 30, tzinfo=timezone.utc))
    fresh_db.session.remove()

    recovered_result = runner.invoke(run_automations)

    assert recovered_result.exit_code == 0, recovered_result.output
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    assert run.id == run_id
    assert run.dispatch_state == "queued"
    assert run.attempt_count == 2
    assert run.queued_job_count == run.intended_job_count
    # The abandoned attempt is still visible as unfinished, which is how an operator spots a dead runner.
    assert [(a.attempt_no, a.owner, a.outcome) for a in run.attempts] == [
        (1, "runner-that-dies", None),
        (2, run.attempts[1].owner, "queued"),
    ]


def test_two_independent_sessions_claim_one_occurrence(
    app, fresh_db, clean_redis, due_forecast_automation
):
    """Exactly one of two concurrent runner sessions wins the same occurrence."""
    import threading

    from flexmeasures.data import db
    from flexmeasures.data.services.automations import (
        claim_due_automation_run,
        get_due_automations,
    )

    now = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
    start_together = threading.Barrier(2, timeout=30)
    outcomes: dict[str, int | None] = {}
    lock = threading.Lock()

    def claim_as(owner: str) -> None:
        # Each thread gets its own app context, and with it its own database session.
        with app.app_context():
            try:
                due_automations = get_due_automations(now)
                start_together.wait()
                claimed = (
                    claim_due_automation_run(due_automations[0], owner=owner)
                    if due_automations
                    else None
                )
                with lock:
                    outcomes[owner] = claimed.run.id if claimed is not None else None
            finally:
                db.session.remove()

    threads = [
        threading.Thread(target=claim_as, args=(owner,))
        for owner in ("runner-a", "runner-b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive(), "a claiming thread did not finish"

    assert sorted(outcomes) == ["runner-a", "runner-b"]
    winners = [owner for owner, run_id in outcomes.items() if run_id is not None]
    assert len(winners) == 1, f"expected exactly one winner, got {outcomes}"
    runs = fresh_db.session.scalars(select(AutomationRun)).all()
    assert len(runs) == 1
    assert runs[0].id == outcomes[winners[0]]
    assert runs[0].claim_owner == winners[0]


def test_completed_dispatch_is_not_redone_after_redis_is_flushed(
    app, fresh_db, clean_redis, due_forecast_automation
):
    """Losing the Redis jobs does not make a completed occurrence run a second time.

    The durable run record, not any Redis key, is what says the occurrence was already dispatched.
    """
    from flexmeasures.cli.jobs import run_automations

    runner = app.test_cli_runner()
    first_result = runner.invoke(run_automations)
    assert first_result.exit_code == 0, first_result.output
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    dispatch_completed_at = run.dispatch_completed_at
    assert dispatch_completed_at is not None

    app.redis_connection.flushdb()
    assert app.queues["forecasting"].count == 0

    second_result = runner.invoke(run_automations)

    assert second_result.exit_code == 0, second_result.output
    assert app.queues["forecasting"].count == 0
    runs = fresh_db.session.scalars(select(AutomationRun)).all()
    assert len(runs) == 1
    fresh_db.session.refresh(run)
    assert run.dispatch_completed_at == dispatch_completed_at
    assert run.attempt_count == 1


def test_multi_cycle_run_records_its_wrap_up_dependencies(
    app, fresh_db, clean_redis, due_forecast_automation
):
    """Every cycle job and the wrap-up job carry the run identity, and the wrap-up waits for the cycles."""
    from flexmeasures.cli.jobs import run_automations

    runner = app.test_cli_runner()
    result = runner.invoke(run_automations)
    assert result.exit_code == 0, result.output
    run = fresh_db.session.scalars(select(AutomationRun)).one()

    cycle_intents = [i for i in run.job_intents if i.kind == "forecast-cycle"]
    wrap_up_intents = [i for i in run.job_intents if i.kind == "forecast-wrap-up"]
    assert len(cycle_intents) > 1, "this automation is expected to need several cycles"
    assert len(wrap_up_intents) == 1
    wrap_up = wrap_up_intents[0]
    assert wrap_up.depends_on == [i.logical_job_key for i in cycle_intents]

    queue = app.queues["forecasting"]
    # The cycle jobs are ready to run, while the wrap-up job waits for them in the deferred registry.
    assert sorted(queue.job_ids) == sorted(i.rq_job_id for i in cycle_intents)
    assert list(queue.deferred_job_registry.get_job_ids()) == [wrap_up.rq_job_id]
    wrap_up_job = queue.fetch_job(wrap_up.rq_job_id)
    assert sorted(wrap_up_job._dependency_ids) == sorted(
        i.rq_job_id for i in cycle_intents
    )
    for intent in run.job_intents:
        job = queue.fetch_job(intent.rq_job_id)
        assert job is not None, f"{intent.logical_job_key} is not in Redis"
        assert job.meta["automation_run_id"] == run.id
        assert job.meta["logical_job_key"] == intent.logical_job_key
        assert job.meta["trigger"]["automation_run_id"] == run.id


def test_worker_success_is_recorded_durably(
    app, fresh_db, clean_redis, due_forecast_automation
):
    """A job which a worker completes is marked succeeded on its durable intent."""
    from rq import SimpleWorker

    from flexmeasures.cli.jobs import run_automations

    runner = app.test_cli_runner()
    assert runner.invoke(run_automations).exit_code == 0
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    queue = app.queues["forecasting"]
    wrap_up = next(i for i in run.job_intents if i.kind == "forecast-wrap-up")

    worker = SimpleWorker([queue], connection=queue.connection)
    worker.perform_job(queue.fetch_job(wrap_up.rq_job_id), queue)

    fresh_db.session.refresh(run)
    fresh_db.session.refresh(wrap_up)
    assert wrap_up.status == "succeeded"
    assert wrap_up.started_at is not None
    assert wrap_up.finished_at is not None
    # The cycle jobs have not run yet, so the run as a whole is still in progress.
    assert run.execution_state == "running"
    assert run.execution_started_at is not None
    assert run.execution_completed_at is None


def test_worker_failure_is_recorded_durably(
    app, fresh_db, clean_redis, due_forecast_automation
):
    """A job which a worker fails is marked failed on its durable intent, with the error kept for diagnosis."""
    from rq import SimpleWorker

    from flexmeasures.cli.jobs import run_automations

    runner = app.test_cli_runner()
    assert runner.invoke(run_automations).exit_code == 0
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    queue = app.queues["forecasting"]
    wrap_up = next(i for i in run.job_intents if i.kind == "forecast-wrap-up")
    cycle = next(i for i in run.job_intents if i.kind == "forecast-cycle")

    # Make the wrap-up job fail by taking away one of the cycle jobs it reports on.
    queue.fetch_job(cycle.rq_job_id).delete()
    worker = SimpleWorker([queue], connection=queue.connection)
    worker.perform_job(queue.fetch_job(wrap_up.rq_job_id), queue)

    fresh_db.session.refresh(run)
    fresh_db.session.refresh(wrap_up)
    assert wrap_up.status == "failed"
    assert wrap_up.last_error_type is not None
    assert run.execution_state == "failed"
    assert run.execution_completed_at is not None
    assert run.last_error_type == wrap_up.last_error_type


def test_run_history_survives_a_new_session(
    app, fresh_db, clean_redis, due_forecast_automation
):
    """Run, attempt and job records are readable again after the application session is thrown away."""
    from flexmeasures.cli.jobs import run_automations

    queue = app.queues["forecasting"]
    original_enqueue_job = queue.enqueue_job
    runner = app.test_cli_runner()

    def fail_before_queueing(job):
        raise RuntimeError("redis unavailable")

    queue.enqueue_job = fail_before_queueing  # type: ignore[method-assign]
    try:
        assert runner.invoke(run_automations).exit_code == 1
    finally:
        queue.enqueue_job = original_enqueue_job  # type: ignore[method-assign]
    assert runner.invoke(run_automations).exit_code == 0

    run_id = fresh_db.session.scalars(select(AutomationRun)).one().id
    fresh_db.session.remove()

    run = fresh_db.session.get(AutomationRun, run_id)
    assert run.attempt_count == 2
    assert run.dispatch_state == "queued"
    assert [(a.attempt_no, a.outcome) for a in run.attempts] == [
        (1, "failed"),
        (2, "queued"),
    ]
    assert run.attempts[0].error_type == "RuntimeError"
    assert run.attempts[0].error_message == "redis unavailable"
    assert run.queued_job_count == run.intended_job_count
    assert all(intent.status == "queued" for intent in run.job_intents)


def test_job_failure_is_recorded_even_after_a_database_error(
    app, fresh_db, clean_redis, due_forecast_automation
):
    """A job which fails on a database error still gets its failure recorded.

    The failing statement leaves the session in an aborted transaction, in which every further statement is refused,
    so recording the failure has to start by putting the session back in a usable state.
    """
    from flexmeasures.cli.jobs import run_automations
    from flexmeasures.data.services.automations import record_automation_job_failed

    runner = app.test_cli_runner()
    assert runner.invoke(run_automations).exit_code == 0
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    run_id = run.id
    logical_job_key = next(
        i.logical_job_key for i in run.job_intents if i.kind == "forecast-cycle"
    )

    # Break the transaction the way a failing statement inside the job would.
    with pytest.raises(DatabaseError):
        fresh_db.session.execute(text("SELECT no_such_function_2393()"))

    record_automation_job_failed(
        run_id, logical_job_key, RuntimeError("the job hit a database error")
    )

    fresh_db.session.remove()
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    failed_intent = next(
        i for i in run.job_intents if i.logical_job_key == logical_job_key
    )
    assert failed_intent.status == "failed"
    assert failed_intent.last_error_type == "RuntimeError"
    assert failed_intent.last_error_message == "the job hit a database error"
    assert run.execution_state == "failed"
    assert run.execution_completed_at is not None


def test_a_later_success_does_not_hide_an_earlier_job_failure(
    app, fresh_db, clean_redis, due_forecast_automation
):
    """A run whose job failed stays failed, even when its remaining jobs go on to succeed.

    The wrap-up job succeeds whatever became of the cycle jobs it reports on, so it must not report the run as
    merely still running and bury the failure an operator needs to see.
    """
    from flexmeasures.cli.jobs import run_automations
    from flexmeasures.data.services.automations import (
        record_automation_job_failed,
        record_automation_job_succeeded,
    )

    runner = app.test_cli_runner()
    assert runner.invoke(run_automations).exit_code == 0
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    cycles = [i for i in run.job_intents if i.kind == "forecast-cycle"]
    wrap_up = next(i for i in run.job_intents if i.kind == "forecast-wrap-up")

    record_automation_job_failed(
        run.id, cycles[0].logical_job_key, RuntimeError("the cycle blew up")
    )
    for cycle in cycles[1:]:
        record_automation_job_succeeded(run.id, cycle.logical_job_key)
    record_automation_job_succeeded(run.id, wrap_up.logical_job_key)

    fresh_db.session.remove()
    run = fresh_db.session.scalars(select(AutomationRun)).one()
    assert run.execution_state == "failed"
    assert run.execution_completed_at is not None
    assert run.last_error_type == "RuntimeError"
    assert sorted(i.status for i in run.job_intents) == sorted(
        ["failed"] + ["succeeded"] * len(run.job_intents[1:])
    )
