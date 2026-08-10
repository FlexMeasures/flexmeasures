"""Regression tests for durable forecast automation occurrence calculation."""

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
            scheduling_cursor=cursor,
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
def test_missed_occurrences_are_coalesced(
    automation_factory, cronstr, cursor, now, expected
):
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


def test_spring_forward_occurrence_runs_at_transition_boundary(
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
    assert persisted.scheduling_cursor == now


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
    assert automation.scheduling_cursor == cursor
