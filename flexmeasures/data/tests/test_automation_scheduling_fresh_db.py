"""Regression tests for durable forecast automation run calculation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from flask import current_app

from flexmeasures.data.models.automations import Automation, AutomationRun
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.services.automations import (
    MISSED_RUN_TOO_OLD,
    DueAutomation,
    claim_due_automation_run,
    get_due_automations,
    skip_stale_automation_runs,
)


@pytest.fixture()
def automation_factory(fresh_db):
    """Create persisted automations with the minimum required relationships."""
    asset_type = GenericAssetType(name="automation scheduling asset type")
    asset = GenericAsset(
        name="automation scheduling asset", generic_asset_type=asset_type
    )
    generator = DataSource(
        name="automation scheduling generator",
        type="forecaster",
        model="TrainPredictPipeline",
    )
    fresh_db.session.add_all([asset, generator])
    fresh_db.session.flush()

    def create_automation(
        *,
        name: str,
        cronstr: str,
        timezone_name: str,
        cursor: datetime,
        active: bool = True,
    ) -> Automation:
        automation = Automation(
            asset=asset,
            generator=generator,
            type="forecasting",
            name=name,
            cronstr=cronstr,
            timezone=timezone_name,
            cursor=cursor,
            active=active,
            parameters={},
        )
        fresh_db.session.add(automation)
        fresh_db.session.commit()
        return automation

    return create_automation


def test_automations_use_independent_timezones(fresh_db, automation_factory):
    cursor = datetime(2026, 1, 15, 5, 59, tzinfo=timezone.utc)
    amsterdam = automation_factory(
        name="Amsterdam morning",
        cronstr="0 7 * * *",
        timezone_name="Europe/Amsterdam",
        cursor=cursor,
    )
    new_york = automation_factory(
        name="New York morning",
        cronstr="0 7 * * *",
        timezone_name="America/New_York",
        cursor=cursor,
    )

    due = get_due_automations(datetime(2026, 1, 15, 6, 0, tzinfo=timezone.utc))

    assert [(item.automation.id, item.scheduled_at) for item in due] == [
        (amsterdam.id, datetime(2026, 1, 15, 6, 0, tzinfo=timezone.utc))
    ]
    assert claim_due_automation_run(due[0]) is not None

    due = get_due_automations(datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc))

    assert [(item.automation.id, item.scheduled_at) for item in due] == [
        (new_york.id, datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc))
    ]


@pytest.mark.parametrize(
    ("cronstr", "cursor", "now", "expected"),
    (
        (
            "0 * * * *",
            datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 2, 1, 10, 5, tzinfo=timezone.utc),
            datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc),
        ),
        (
            "*/5 * * * *",
            datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 2, 1, 10, 17, tzinfo=timezone.utc),
            datetime(2026, 2, 1, 10, 15, tzinfo=timezone.utc),
        ),
    ),
)
def test_missed_runs_are_coalesced(automation_factory, cronstr, cursor, now, expected):
    automation = automation_factory(
        name="Catch-up",
        cronstr=cronstr,
        timezone_name="UTC",
        cursor=cursor,
    )

    due = get_due_automations(now)

    assert [(item.automation.id, item.scheduled_at) for item in due] == [
        (automation.id, expected)
    ]


@pytest.mark.parametrize(
    ("max_catchup", "expected_skipped"),
    (
        # At 11:05, the missed 10:00 run is 65 minutes old.
        (timedelta(minutes=60), True),
        (timedelta(minutes=65), False),
        (timedelta(0), True),
    ),
)
def test_stale_missed_runs_are_skipped(
    fresh_db, automation_factory, max_catchup, expected_skipped
):
    automation = automation_factory(
        name="Bounded catch-up",
        cronstr="0 10 * * *",
        timezone_name="UTC",
        cursor=datetime(2026, 1, 31, 10, 0, tzinfo=timezone.utc),
    )
    now = datetime(2026, 2, 1, 11, 5, tzinfo=timezone.utc)
    missed_run = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)

    skipped = skip_stale_automation_runs(max_catchup, now)

    if expected_skipped:
        assert [(run.automation_id, run.scheduled_at) for run in skipped] == [
            (automation.id, missed_run)
        ]
        # the skip is recorded as a run, saying why, so that it shows up with the automation's runs
        run = fresh_db.session.scalars(select(AutomationRun)).one()
        assert run.execution_state == "skipped"
        assert run.execution_completed_at is not None
        assert run.dispatch_completed_at is not None
        assert run.last_error_type == MISSED_RUN_TOO_OLD
        assert "--max-catchup" in run.last_error_message
        # the cursor moved past the skipped run, so it is not caught up afterwards either
        fresh_db.session.refresh(automation)
        assert automation.cursor == missed_run
        assert get_due_automations(now) == []
    else:
        assert skipped == []
        assert fresh_db.session.scalars(select(AutomationRun)).all() == []
        assert [item.scheduled_at for item in get_due_automations(now)] == [missed_run]

    # either way, the automation resumes on its next scheduled run
    next_run = datetime(2026, 2, 2, 10, 0, tzinfo=timezone.utc)
    assert [item.scheduled_at for item in get_due_automations(next_run)] == [next_run]


@pytest.mark.parametrize(
    ("dispatch_state", "queued_a_job", "expected_skipped"),
    (
        # A runner died after claiming the run, before it queued anything.
        ("claimed", False, True),
        # Its attempt failed before queueing anything, and is up for a retry.
        ("failed", False, True),
        # It queued part of its jobs, so it is left to queue the rest, rather than to stay half done.
        ("partially_queued", True, False),
    ),
)
def test_stale_unfinished_runs_are_skipped(
    fresh_db, automation_factory, dispatch_state, queued_a_job, expected_skipped
):
    """A run a runner left unfinished is not resumed when it is older than the bound, unless it already queued a job."""
    automation = automation_factory(
        name="Left behind",
        cronstr="0 8 * * *",
        timezone_name="UTC",
        cursor=datetime(2026, 1, 31, 8, 0, tzinfo=timezone.utc),
    )
    scheduled_at = datetime(2026, 2, 1, 8, 0, tzinfo=timezone.utc)
    due_automation = DueAutomation(
        automation=automation,
        scheduled_at=scheduled_at,
        expected_cursor=automation.cursor,
        expected_cronstr=automation.cronstr,
        expected_timezone=automation.timezone,
    )
    run = claim_due_automation_run(due_automation).run
    run.dispatch_state = dispatch_state
    run.claim_expires_at = datetime(2026, 2, 1, 8, 5, tzinfo=timezone.utc)
    if queued_a_job:
        run.first_enqueued_at = datetime(2026, 2, 1, 8, 0, 30, tzinfo=timezone.utc)
    fresh_db.session.commit()
    # Three hours later, the runner restarts with a bound of an hour, after the run's own time came and went.
    now = datetime(2026, 2, 1, 11, 0, tzinfo=timezone.utc)

    skipped = skip_stale_automation_runs(timedelta(minutes=60), now)

    fresh_db.session.refresh(run)
    if expected_skipped:
        assert [skipped_run.id for skipped_run in skipped] == [run.id]
        assert run.execution_state == "skipped"
        assert run.dispatch_completed_at is not None
        assert run.claim_owner is None
        assert run.last_error_type == MISSED_RUN_TOO_OLD
    else:
        assert skipped == []
        assert run.execution_state == "pending"
        assert run.dispatch_completed_at is None


def test_zero_catchup_keeps_the_run_due_this_minute(fresh_db, automation_factory):
    automation = automation_factory(
        name="On time",
        cronstr="0 * * * *",
        timezone_name="UTC",
        cursor=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
    )
    now = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)

    assert skip_stale_automation_runs(timedelta(0), now) == []
    assert [
        (item.automation.id, item.scheduled_at) for item in get_due_automations(now)
    ] == [(automation.id, now)]


def test_spring_forward_run_happens_at_transition_boundary(
    automation_factory,
):
    automation = automation_factory(
        name="Skipped Amsterdam time",
        cronstr="30 2 * * *",
        timezone_name="Europe/Amsterdam",
        cursor=datetime(2026, 3, 29, 0, 59, tzinfo=timezone.utc),
    )

    due = get_due_automations(datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc))

    assert [(item.automation.id, item.scheduled_at) for item in due] == [
        (automation.id, datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc))
    ]
    assert claim_due_automation_run(due[0]) is not None
    assert get_due_automations(datetime(2026, 3, 29, 1, 1, tzinfo=timezone.utc)) == []


def test_fall_back_wall_time_runs_only_once(fresh_db, automation_factory):
    automation = automation_factory(
        name="Repeated Amsterdam time",
        cronstr="30 2 * * *",
        timezone_name="Europe/Amsterdam",
        cursor=datetime(2026, 10, 25, 0, 29, tzinfo=timezone.utc),
    )

    first_fold_due = get_due_automations(
        datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
    )
    assert [(item.automation.id, item.scheduled_at) for item in first_fold_due] == [
        (automation.id, datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc))
    ]
    assert claim_due_automation_run(first_fold_due[0]) is not None

    fresh_db.session.remove()
    second_fold_due = get_due_automations(
        datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)
    )

    assert second_fold_due == []


def test_fall_back_resume_coalesces_completed_first_fold(
    automation_factory,
):
    automation = automation_factory(
        name="Fall-back downtime",
        cronstr="* * * * *",
        timezone_name="Europe/Amsterdam",
        cursor=datetime(2026, 10, 24, 23, 59, tzinfo=timezone.utc),
    )

    due = get_due_automations(datetime(2026, 10, 25, 1, 15, tzinfo=timezone.utc))

    assert [(item.automation.id, item.scheduled_at) for item in due] == [
        (automation.id, datetime(2026, 10, 25, 0, 59, tzinfo=timezone.utc))
    ]


def test_persisted_cursor_survives_restart(fresh_db, automation_factory):
    automation = automation_factory(
        name="Persistent cursor",
        cronstr="0 10 * * *",
        timezone_name="UTC",
        cursor=datetime(2026, 2, 1, 9, 59, tzinfo=timezone.utc),
    )
    now = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)
    due = get_due_automations(now)
    assert claim_due_automation_run(due[0]) is not None
    automation_id = automation.id

    fresh_db.session.remove()

    assert get_due_automations(now) == []
    persisted = fresh_db.session.get(Automation, automation_id)
    assert persisted.cursor == now


def test_inactive_automation_is_not_due(automation_factory):
    cursor = datetime(2026, 2, 1, 9, 59, tzinfo=timezone.utc)
    automation = automation_factory(
        name="Inactive",
        cronstr="* * * * *",
        timezone_name="UTC",
        cursor=cursor,
        active=False,
    )

    assert get_due_automations(datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)) == []
    assert automation.cursor == cursor


def test_invalid_cron_does_not_hide_other_due_automations(automation_factory, mocker):
    cursor = datetime(2026, 2, 1, 9, 59, tzinfo=timezone.utc)
    invalid = automation_factory(
        name="Impossible date",
        cronstr="0 0 31 2 *",
        timezone_name="UTC",
        cursor=cursor,
    )
    valid = automation_factory(
        name="Valid recurrence",
        cronstr="* * * * *",
        timezone_name="UTC",
        cursor=cursor,
    )

    # Assert on the logger rather than on caplog: building an app reconfigures logging and
    # replaces the root handlers, so caplog stops capturing for the rest of the test session
    # once any earlier test has built one.
    log_error = mocker.patch.object(current_app.logger, "error")

    due = get_due_automations(datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc))

    assert [item.automation.id for item in due] == [valid.id]
    assert log_error.call_count == 1
    assert log_error.call_args.args[0].startswith("Skipping automation")
    assert log_error.call_args.args[1] == invalid.id


def test_claim_rejects_automation_deactivated_after_discovery(
    fresh_db, automation_factory
):
    cursor = datetime(2026, 2, 1, 9, 59, tzinfo=timezone.utc)
    automation = automation_factory(
        name="Deactivate race",
        cronstr="* * * * *",
        timezone_name="UTC",
        cursor=cursor,
    )
    due = get_due_automations(datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc))[0]

    automation.active = False
    fresh_db.session.commit()

    assert claim_due_automation_run(due) is None
    assert automation.cursor == cursor


@pytest.mark.parametrize(
    ("field", "new_value"),
    (("cronstr", "0 11 * * *"), ("timezone", "Europe/Amsterdam")),
)
def test_claim_rejects_recurrence_edited_after_discovery(
    fresh_db, automation_factory, field, new_value
):
    cursor = datetime(2026, 2, 1, 9, 59, tzinfo=timezone.utc)
    automation = automation_factory(
        name="Edit race",
        cronstr="* * * * *",
        timezone_name="UTC",
        cursor=cursor,
    )
    due = get_due_automations(datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc))[0]

    setattr(automation, field, new_value)
    fresh_db.session.commit()

    assert claim_due_automation_run(due) is None
    assert automation.cursor == cursor


def test_claim_rejects_cursor_changed_after_discovery(fresh_db, automation_factory):
    cursor = datetime(2026, 2, 1, 9, 58, tzinfo=timezone.utc)
    automation = automation_factory(
        name="Cursor race",
        cronstr="* * * * *",
        timezone_name="UTC",
        cursor=cursor,
    )
    due = get_due_automations(datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc))[0]
    newer_cursor = datetime(2026, 2, 1, 9, 59, tzinfo=timezone.utc)

    automation.cursor = newer_cursor
    fresh_db.session.commit()

    assert claim_due_automation_run(due) is None
    assert automation.cursor == newer_cursor


def test_claim_allows_name_edit_after_discovery(fresh_db, automation_factory):
    automation = automation_factory(
        name="Old display name",
        cronstr="* * * * *",
        timezone_name="UTC",
        cursor=datetime(2026, 2, 1, 9, 59, tzinfo=timezone.utc),
    )
    due = get_due_automations(datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc))[0]

    automation.name = "New display name"
    fresh_db.session.commit()

    assert claim_due_automation_run(due) is not None


def test_claim_rejects_automation_deleted_after_discovery(fresh_db, automation_factory):
    automation = automation_factory(
        name="Delete race",
        cronstr="* * * * *",
        timezone_name="UTC",
        cursor=datetime(2026, 2, 1, 9, 59, tzinfo=timezone.utc),
    )
    due = get_due_automations(datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc))[0]

    fresh_db.session.delete(automation)
    fresh_db.session.commit()

    assert claim_due_automation_run(due) is None
