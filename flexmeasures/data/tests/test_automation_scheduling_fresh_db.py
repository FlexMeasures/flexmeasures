"""Regression tests for durable forecast automation run calculation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.services.automations import (
    claim_due_automation,
    get_due_automations,
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
            type="forecasts",
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
    assert claim_due_automation(due[0]) is True

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
    assert claim_due_automation(due[0]) is True
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
    assert claim_due_automation(first_fold_due[0]) is True

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
    assert claim_due_automation(due[0]) is True
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


def test_invalid_cron_does_not_hide_other_due_automations(automation_factory, caplog):
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

    due = get_due_automations(datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc))

    assert [item.automation.id for item in due] == [valid.id]
    assert f"Skipping automation {invalid.id}" in caplog.text


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

    assert claim_due_automation(due) is False
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

    assert claim_due_automation(due) is False
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

    assert claim_due_automation(due) is False
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

    assert claim_due_automation(due) is True


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

    assert claim_due_automation(due) is False
