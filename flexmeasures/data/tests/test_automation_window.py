"""How an automation resolves the window each of its runs covers, from offsets and a duration."""

from datetime import datetime, timezone

import pandas as pd
import pytest
from marshmallow import ValidationError

from flexmeasures.data.services.automations import (
    prepare_report_parameters,
    resolve_automation_window,
    validate_automation_window,
)

# A run due at noon in Amsterdam, on the Friday before daylight saving time starts.
SCHEDULED_AT = datetime(2026, 3, 27, 11, 0, tzinfo=timezone.utc)
TIMEZONE = "Europe/Amsterdam"


@pytest.mark.parametrize(
    "timing, expected_start, expected_duration",
    [
        # tomorrow, as a start and a duration.
        (
            {"start-offset": "1D,DB", "duration": "P1D"},
            "2026-03-28T00:00:00+01:00",
            "P1D",
        ),
        # the day after tomorrow, as two offsets: the day the clocks go forward, which lasts 23 hours.
        (
            {"start-offset": "2D,DB", "end-offset": "3D,DB"},
            "2026-03-29T00:00:00+01:00",
            "PT23H",
        ),
        # tomorrow, as an end and a duration.
        (
            {"end-offset": "2D,DB", "duration": "P1D"},
            "2026-03-28T00:00:00+01:00",
            "P1D",
        ),
    ],
)
def test_schedule_automation_window_follows_its_offsets(
    app, timing, expected_start, expected_duration
):
    """A schedule's window is a start and a duration, whichever two of the three fields describe it."""
    message = resolve_automation_window(
        timing,
        "scheduling",
        TIMEZONE,
        SCHEDULED_AT,
    )
    assert "start-offset" not in message and "end-offset" not in message
    assert pd.Timestamp(message["start"]) == pd.Timestamp(expected_start)
    assert message["duration"] == expected_duration


def test_forecast_automation_window_is_believed_when_it_is_computed(
    app, freeze_server_now
):
    """An offset sets the forecast's start, and a forecast with a start is believed at that start, unless given a prior.

    An automation's forecast is computed at the run time, so that is when it is believed, as it would be without offsets.
    """
    freeze_server_now(datetime(2026, 3, 27, 11, 0, 30, tzinfo=timezone.utc))
    message = resolve_automation_window(
        {"sensor": 1, "start-offset": "1D,DB", "end-offset": "2D,DB"},
        "forecasting",
        TIMEZONE,
        SCHEDULED_AT,
    )
    assert pd.Timestamp(message["start"]) == pd.Timestamp("2026-03-28T00:00:00+01:00")
    assert pd.Timestamp(message["end"]) == pd.Timestamp("2026-03-29T00:00:00+01:00")
    assert "duration" not in message
    assert pd.Timestamp(message["prior"]) == pd.Timestamp("2026-03-27T11:00:30+00:00")


def test_a_delayed_run_still_covers_the_window_it_was_due_for(app, freeze_server_now):
    """Offsets apply to the claimed cron occurrence, so a run that only happens after midnight still schedules the day it was due for."""
    freeze_server_now(datetime(2026, 3, 27, 23, 30, tzinfo=timezone.utc))
    message = resolve_automation_window(
        {"start-offset": "1D,DB", "duration": "P1D"},
        "scheduling",
        TIMEZONE,
        SCHEDULED_AT,
    )
    assert pd.Timestamp(message["start"]) == pd.Timestamp("2026-03-28T00:00:00+01:00")


def test_without_offsets_the_data_generators_own_defaults_apply(app):
    """Without offsets, nothing is resolved, so a forecast or schedule starts at the run time, which keeps a caught-up run current."""
    parameters = {"duration": "PT12H"}
    assert (
        resolve_automation_window(parameters, "scheduling", TIMEZONE, SCHEDULED_AT)
        == parameters
    )


@pytest.mark.parametrize(
    "timing",
    [
        {"start-offset": "-1D,DB", "end-offset": "DB"},
        {"start-offset": "-1D,DB", "duration": "P1D"},
        {"end-offset": "DB", "duration": "P1D"},
    ],
)
def test_report_automation_window_takes_a_duration_for_either_offset(app, timing):
    """A report's window is a start and an end, whichever two of the three fields describe it."""
    message = prepare_report_parameters(
        timing, "0 12 * * *", TIMEZONE, scheduled_at=SCHEDULED_AT
    )
    assert pd.Timestamp(message["start"]) == pd.Timestamp("2026-03-26T00:00:00+01:00")
    assert pd.Timestamp(message["end"]) == pd.Timestamp("2026-03-27T00:00:00+01:00")
    assert "duration" not in message


@pytest.mark.parametrize(
    "automation_type, timing, error",
    [
        (
            "scheduling",
            {"start-offset": "DB", "end-offset": "1D,DB", "duration": "P1D"},
            "not all three",
        ),
        ("forecasting", {"end-offset": "1D,DB"}, "along with an 'end-offset'"),
        ("scheduling", {"end-offset": "1D,DB"}, "along with an 'end-offset'"),
        (
            "reporting",
            {"duration": "P1D"},
            "along with a report automation's 'duration'",
        ),
        ("reporting", {"end-offset": "DB", "duration": "one day"}, "Invalid duration"),
        ("forecasting", {"start-offset": "P1D"}, "Invalid start-offset"),
        (
            "scheduling",
            {"start-offset": "1D,DB", "duration": "PT0H"},
            "must be positive",
        ),
        ("reporting", {"end-offset": "DB", "duration": "-P1D"}, "must be positive"),
        ("forecasting", {"start-offset": "DB", "duration": "-P1M"}, "must be positive"),
    ],
)
def test_a_window_the_runs_cannot_resolve_is_refused(automation_type, timing, error):
    with pytest.raises(ValidationError, match=error):
        validate_automation_window(timing, automation_type)


@pytest.mark.parametrize(
    "automation_type, timing",
    [
        ("forecasting", {}),
        ("forecasting", {"duration": "PT12H"}),
        ("scheduling", {"start-offset": "1D,DB"}),
        ("scheduling", {"end-offset": "2D,DB", "duration": "P1D"}),
        ("reporting", {}),
        ("reporting", {"end-offset": "DB"}),
        ("reporting", {"start-offset": "-1D,DB"}),
    ],
)
def test_a_window_the_runs_can_resolve_is_accepted(automation_type, timing):
    validate_automation_window(timing, automation_type)


@pytest.mark.parametrize("automation_type", ["forecasting", "scheduling"])
def test_offsets_that_end_before_they_start_are_refused(app, automation_type):
    with pytest.raises(ValidationError, match="does not end after it starts"):
        resolve_automation_window(
            {"start-offset": "1D,DB", "end-offset": "DB"},
            automation_type,
            TIMEZONE,
            SCHEDULED_AT,
        )


def test_report_offsets_that_end_before_they_start_are_refused(app):
    with pytest.raises(ValidationError, match="does not end after it starts"):
        prepare_report_parameters(
            {"start-offset": "DB", "end-offset": "-1D,DB"},
            "0 12 * * *",
            TIMEZONE,
            scheduled_at=SCHEDULED_AT,
        )


@pytest.mark.parametrize("automation_type", ["forecasting", "scheduling"])
def test_an_end_offset_stored_without_a_duration_is_named(app, automation_type):
    """Creating such an automation is refused, so resolving one says which field is missing, rather than raising a bare KeyError."""
    with pytest.raises(ValidationError, match="needs a 'start-offset' or a 'duration'"):
        resolve_automation_window(
            {"end-offset": "1D,DB"}, automation_type, TIMEZONE, SCHEDULED_AT
        )


def test_a_report_does_not_reach_back_past_what_it_already_covered(app, caplog):
    """An "end-offset" alone starts where the last successful report ended, which a backward offset can leave behind.

    The run then reports on nothing, rather than on a window that ends before it starts.
    """
    with caplog.at_level("WARNING"):
        message = prepare_report_parameters(
            {"end-offset": "-1D,DB"}, "0 12 * * *", TIMEZONE, scheduled_at=SCHEDULED_AT
        )
    assert pd.Timestamp(message["start"]) == pd.Timestamp(message["end"])
    assert "Reporting on nothing for this run." in caplog.text
