"""Tests for deleting the records of automation runs older than their time-to-live (FLEXMEASURES_AUTOMATION_DBLOGS_TTL)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.automations import (
    Automation,
    AutomationRun,
    AutomationRunAttempt,
    AutomationRunJob,
)
from flexmeasures.data.services.automation_pruning import (
    AUTOMATION_RUN_PRUNING_REDIS_KEY,
    prune_automation_runs,
)

NOW = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
STUCK_AFTER = timedelta(hours=6)


@pytest.fixture(scope="function")
def clean_redis(app):
    app.redis_connection.flushdb()
    yield
    app.redis_connection.flushdb()


@pytest.fixture()
def automation(app, fresh_db, setup_fresh_test_forecast_data, freeze_server_now):
    """Create a forecast automation, which is not due at the frozen minute, so that running automations only prunes."""
    from flexmeasures.cli.data_add import add_automation

    freeze_server_now(NOW)
    sensor = setup_fresh_test_forecast_data["solar-sensor"]
    result = app.test_cli_runner().invoke(
        add_automation,
        to_flags(
            {
                "asset": sensor.generic_asset_id,
                "name": "Pruned forecasts",
                "cron": "0 12 * * *",
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
    return fresh_db.session.scalars(select(Automation)).one()


def add_run(db, automation: Automation, age: timedelta, **columns) -> int:
    """Record a run that was scheduled ``age`` before now, which succeeded unless the test says otherwise, and return its ID."""
    scheduled_at = NOW - age
    columns = {
        "automation_type": automation.type,
        "dispatch_state": "queued",
        "dispatch_completed_at": scheduled_at,
        "execution_state": "succeeded",
        "execution_started_at": scheduled_at,
        "execution_completed_at": scheduled_at,
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
    return run.id


def remaining_run_ids(db) -> set[int]:
    db.session.expire_all()
    return set(db.session.scalars(select(AutomationRun.id)).all())


def prune(**kwargs) -> int:
    kwargs = {
        "now": NOW,
        "ttl_setting": timedelta(days=60),
        "stuck_after": STUCK_AFTER,
        **kwargs,
    }
    return prune_automation_runs(**kwargs)


def test_expired_runs_are_deleted_with_their_attempts_and_jobs(fresh_db, automation):
    """A run older than its time-to-live is deleted, and its attempts and jobs go with it."""
    expired = add_run(fresh_db, automation, timedelta(days=61))
    fresh_db.session.add(
        AutomationRunAttempt(
            run_id=expired, attempt_no=1, owner="runner", started_at=NOW
        )
    )
    fresh_db.session.add(
        AutomationRunJob(
            run_id=expired,
            logical_job_key="forecast-wrap-up",
            rq_job_id="pruned-job",
            kind="forecast-wrap-up",
            status="succeeded",
        )
    )
    fresh_db.session.commit()
    kept = add_run(fresh_db, automation, timedelta(days=59))
    latest = add_run(fresh_db, automation, timedelta(days=1))

    assert prune() == 1

    assert remaining_run_ids(fresh_db) == {kept, latest}
    assert fresh_db.session.scalar(select(func.count(AutomationRunAttempt.id))) == 0
    assert fresh_db.session.scalar(select(func.count(AutomationRunJob.id))) == 0


def test_the_latest_run_of_an_automation_is_kept_however_old(fresh_db, automation):
    """An automation that stopped running still shows how it last went."""
    add_run(fresh_db, automation, timedelta(days=200))
    latest = add_run(fresh_db, automation, timedelta(days=100))

    assert prune() == 1

    assert remaining_run_ids(fresh_db) == {latest}


def test_each_automation_type_has_its_own_time_to_live(fresh_db, automation):
    """Named types get their own time-to-live, other types the default, and None keeps a type's runs forever."""
    ingestion = add_run(
        fresh_db, automation, timedelta(days=15), automation_type="ingestion"
    )
    plugin_type = add_run(
        fresh_db, automation, timedelta(days=31), automation_type="plugin-type"
    )
    young_plugin_type = add_run(
        fresh_db, automation, timedelta(days=29), automation_type="plugin-type"
    )
    kept_forever = add_run(
        fresh_db, automation, timedelta(days=1000), automation_type="scheduling"
    )
    latest = add_run(fresh_db, automation, timedelta(days=1))

    pruned = prune(
        ttl_setting={
            "default": timedelta(days=30),
            "ingestion": timedelta(days=14),
            "scheduling": None,
        }
    )

    assert pruned == 2
    remaining = remaining_run_ids(fresh_db)
    assert ingestion not in remaining
    assert plugin_type not in remaining
    assert remaining == {young_plugin_type, kept_forever, latest}


@pytest.mark.parametrize(
    "ttl_setting",
    [None, {"ingestion": timedelta(days=1)}],
    ids=["switched off", "type not named and no default"],
)
def test_runs_are_kept_without_a_time_to_live(fresh_db, automation, ttl_setting):
    """Without a time-to-live for its type, a run is kept forever."""
    old = add_run(fresh_db, automation, timedelta(days=1000))
    latest = add_run(fresh_db, automation, timedelta(days=1))

    assert prune(ttl_setting=ttl_setting) == 0

    assert remaining_run_ids(fresh_db) == {old, latest}


def test_a_run_being_dispatched_is_kept(fresh_db, automation):
    """A run that a runner holds a live claim on is kept, and one whose claim expired is not."""
    claimed = add_run(
        fresh_db,
        automation,
        timedelta(days=100),
        dispatch_state="claimed",
        execution_state="pending",
        claim_owner="runner",
        claim_expires_at=NOW + timedelta(minutes=5),
    )
    claim_expired = add_run(
        fresh_db,
        automation,
        timedelta(days=99),
        dispatch_state="claimed",
        execution_state="pending",
        claim_owner="runner",
        claim_expires_at=NOW - timedelta(minutes=5),
    )
    latest = add_run(fresh_db, automation, timedelta(days=1))

    assert prune() == 1

    remaining = remaining_run_ids(fresh_db)
    assert claim_expired not in remaining
    assert remaining == {claimed, latest}


def test_an_unreported_failure_is_kept_until_the_monitor_reported_it(
    fresh_db, automation
):
    """A failed or stuck run of a monitored automation is kept until it is reported, and deleted afterwards."""
    failed = add_run(
        fresh_db, automation, timedelta(days=100), execution_state="failed"
    )
    stuck = add_run(
        fresh_db,
        automation,
        timedelta(days=99),
        execution_state="running",
        execution_completed_at=None,
    )
    reported = add_run(
        fresh_db,
        automation,
        timedelta(days=98),
        execution_state="failed",
        alerted_at=NOW - timedelta(days=97),
    )
    latest = add_run(fresh_db, automation, timedelta(days=1))

    assert prune() == 1

    remaining = remaining_run_ids(fresh_db)
    assert reported not in remaining
    assert remaining == {failed, stuck, latest}

    # Once monitoring is switched off, nothing will report them, so they go, too.
    automation.monitored = False
    fresh_db.session.commit()

    assert prune() == 2

    assert remaining_run_ids(fresh_db) == {latest}


def test_a_run_that_never_finished_is_deleted_once_expired(fresh_db, automation):
    """A run whose jobs never reported back, which nothing will finish any more, does not stay forever."""
    unfinished = add_run(
        fresh_db,
        automation,
        timedelta(days=100),
        execution_state="pending",
        execution_started_at=None,
        execution_completed_at=None,
    )
    latest = add_run(fresh_db, automation, timedelta(days=1))

    assert prune() == 1

    remaining = remaining_run_ids(fresh_db)
    assert unfinished not in remaining
    assert remaining == {latest}


def test_runs_are_deleted_in_batches_within_the_time_budget(fresh_db, automation):
    """Batches go on until no expired run is left, but no new batch starts once the time budget is spent."""
    for days in range(100, 105):
        add_run(fresh_db, automation, timedelta(days=days))
    latest = add_run(fresh_db, automation, timedelta(days=1))

    assert prune(batch_size=2, time_budget=timedelta(0)) == 2
    assert len(remaining_run_ids(fresh_db)) == 4

    assert prune(batch_size=2) == 3
    assert remaining_run_ids(fresh_db) == {latest}


def test_running_automations_prunes_at_most_once_an_hour(
    app, fresh_db, clean_redis, automation, freeze_server_now
):
    """`flexmeasures jobs run-automations` prunes, and then leaves pruning alone for an hour."""
    from flexmeasures.cli.jobs import run_automations

    add_run(fresh_db, automation, timedelta(days=100))
    latest = add_run(fresh_db, automation, timedelta(days=1))

    result = app.test_cli_runner().invoke(run_automations)

    assert result.exit_code == 0, result.output
    assert "Deleted the records of 1 automation run(s)" in result.output
    assert remaining_run_ids(fresh_db) == {latest}

    expired = add_run(fresh_db, automation, timedelta(days=99))
    freeze_server_now(NOW + timedelta(minutes=1))

    result = app.test_cli_runner().invoke(run_automations)

    assert result.exit_code == 0, result.output
    assert "Deleted the records" not in result.output
    assert remaining_run_ids(fresh_db) == {expired, latest}

    # The hour is up once its Redis key expired.
    app.redis_connection.delete(AUTOMATION_RUN_PRUNING_REDIS_KEY)

    result = app.test_cli_runner().invoke(run_automations)

    assert result.exit_code == 0, result.output
    assert remaining_run_ids(fresh_db) == {latest}
