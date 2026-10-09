"""Tests for the next scheduled run shown in the automations UI."""

from datetime import datetime, timezone

import pytest

from flexmeasures.data.models.automations import Automation
from flexmeasures.data.services.automations import get_next_scheduled_run


def automation(cronstr: str, timezone_name: str, active: bool = True) -> Automation:
    return Automation(cronstr=cronstr, timezone=timezone_name, active=active)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (
            datetime(2026, 1, 15, 4, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 15, 5, 0, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 6, 15, 3, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 15, 4, 0, tzinfo=timezone.utc),
        ),
    ],
)
def test_next_run_follows_automation_timezone(now, expected):
    scheduled = automation("0 6 * * *", "Europe/Amsterdam")

    assert get_next_scheduled_run(scheduled, now) == expected


def test_next_run_uses_transition_boundary_for_skipped_spring_time():
    scheduled = automation("30 2 * * *", "Europe/Amsterdam")

    assert get_next_scheduled_run(
        scheduled, datetime(2026, 3, 29, 0, 59, tzinfo=timezone.utc)
    ) == datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc)
    assert get_next_scheduled_run(
        scheduled, datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc)
    ) == datetime(2026, 3, 30, 0, 30, tzinfo=timezone.utc)


def test_next_run_skips_second_fall_fold():
    scheduled = automation("30 2 * * *", "Europe/Amsterdam")

    assert get_next_scheduled_run(
        scheduled, datetime(2026, 10, 25, 0, 29, tzinfo=timezone.utc)
    ) == datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
    assert get_next_scheduled_run(
        scheduled, datetime(2026, 10, 25, 1, 15, tzinfo=timezone.utc)
    ) == datetime(2026, 10, 26, 1, 30, tzinfo=timezone.utc)


def test_every_minute_skips_repeated_fall_minutes():
    scheduled = automation("* * * * *", "Europe/Amsterdam")

    assert get_next_scheduled_run(
        scheduled, datetime(2026, 10, 25, 1, 15, tzinfo=timezone.utc)
    ) == datetime(2026, 10, 25, 2, 0, tzinfo=timezone.utc)


def test_inactive_and_invalid_automations_have_no_next_run():
    now = datetime(2026, 6, 15, 3, 0, tzinfo=timezone.utc)

    assert get_next_scheduled_run(automation("* * * * *", "UTC", False), now) is None
    assert get_next_scheduled_run(automation("not a cron", "UTC"), now) is None


def test_next_run_rejects_naive_now():
    with pytest.raises(ValueError, match="timezone-aware"):
        get_next_scheduled_run(automation("0 6 * * *", "UTC"), datetime(2026, 6, 15))
