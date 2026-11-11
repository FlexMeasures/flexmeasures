import json
from datetime import date, time, timedelta

import numpy as np
import pandas as pd
import pytest

from flexmeasures.utils.recurrence import (
    RecurrenceError,
    expand_wall_clock_recurrence,
)


def minute_of_day_pattern(
    tz: str, start: str, duration: timedelta, resolution: timedelta
) -> pd.Series:
    """Make a pattern whose values are the local minute-of-day of each slot, so a value tells which local time it came from."""
    index = pd.date_range(
        pd.Timestamp(start, tz=tz),
        pd.Timestamp(start, tz=tz) + duration,
        freq=resolution,
        inclusive="left",
    )
    return pd.Series(index.hour * 60.0 + index.minute, index=index)


def local_minute_of_day(index: pd.DatetimeIndex) -> np.ndarray:
    return (index.hour * 60 + index.minute).to_numpy(dtype=float)


QUARTER = timedelta(minutes=15)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


@pytest.mark.parametrize(
    "tz, resolution, transition_date, kind, shift, exp_omitted, exp_duplicated",
    [
        # Northern hemisphere: forward in March, back in October.
        (
            "Europe/Amsterdam",
            QUARTER,
            date(2026, 3, 29),
            "spring_forward",
            HOUR,
            [time(2, 0), time(2, 15), time(2, 30), time(2, 45)],
            [],
        ),
        (
            "Europe/Amsterdam",
            QUARTER,
            date(2026, 10, 25),
            "fall_back",
            HOUR,
            [],
            [time(2, 0), time(2, 15), time(2, 30), time(2, 45)],
        ),
        # Southern hemisphere: the same months, in the opposite direction.
        (
            "Australia/Sydney",
            QUARTER,
            date(2026, 4, 5),
            "fall_back",
            HOUR,
            [],
            [time(2, 0), time(2, 15), time(2, 30), time(2, 45)],
        ),
        (
            "Australia/Sydney",
            HOUR,
            date(2026, 10, 4),
            "spring_forward",
            HOUR,
            [time(2, 0)],
            [],
        ),
        # Lord Howe Island shifts its clocks by 30 minutes, which a 15-minute resolution can follow.
        (
            "Australia/Lord_Howe",
            QUARTER,
            date(2026, 4, 5),
            "fall_back",
            timedelta(minutes=30),
            [],
            [time(1, 30), time(1, 45)],
        ),
        (
            "Australia/Lord_Howe",
            QUARTER,
            date(2026, 10, 4),
            "spring_forward",
            timedelta(minutes=30),
            [time(2, 0), time(2, 15)],
            [],
        ),
    ],
)
def test_daily_repeat_follows_the_wall_clock_across_dst(
    tz, resolution, transition_date, kind, shift, exp_omitted, exp_duplicated
):
    """Repeat one day across a clock change: every value lands on its own local time, and the report says what the change did."""
    pattern_day = transition_date - timedelta(days=2)
    pattern = minute_of_day_pattern(tz, str(pattern_day), DAY, resolution)

    expanded, report = expand_wall_clock_recurrence(
        pattern, transition_date + timedelta(days=1), tz, resolution
    )

    # Each repeat keeps the local time-of-day of its source slot.
    assert (expanded.to_numpy() == local_minute_of_day(expanded.index)).all()
    assert expanded.index.tz is not None

    # The transition day loses or gains exactly the slots the clock change skips or repeats.
    slots_per_day = expanded.groupby(expanded.index.date).size()
    slots_per_normal_day = DAY // resolution
    assert slots_per_day[transition_date - timedelta(days=1)] == slots_per_normal_day
    assert slots_per_day[transition_date] == slots_per_normal_day - len(
        exp_omitted
    ) + len(exp_duplicated)

    # The result is one contiguous series, so it can be sent as one array.
    assert (expanded.index.to_series().diff().iloc[1:] == resolution).all()

    assert report.mode == "wall_clock"
    assert report.n_occurrences == 3
    (transition,) = report.transitions
    assert transition.date == transition_date
    assert transition.kind == kind
    assert transition.shift == shift
    assert list(transition.omitted) == exp_omitted
    assert list(transition.duplicated) == exp_duplicated
    assert transition.n_omitted == len(exp_omitted)
    assert transition.n_duplicated == len(exp_duplicated)


def test_repeat_falls_back_to_absolute_steps_if_the_resolution_cannot_follow_the_clock():
    """An hourly sensor cannot follow Lord Howe Island's 30-minute clock change, so it repeats every 24 hours instead."""
    tz = "Australia/Lord_Howe"
    pattern = minute_of_day_pattern(tz, "2026-04-03", DAY, HOUR)

    expanded, report = expand_wall_clock_recurrence(pattern, date(2026, 4, 6), tz, HOUR)

    assert report.mode == "absolute"
    assert "PT30M" in report.fallback_reason
    (transition,) = report.transitions
    assert transition.date == date(2026, 4, 5)
    assert transition.n_omitted == transition.n_duplicated == 0

    # Values stay exactly a whole number of 24 hours away from their source, and on the hourly grid.
    assert (expanded.index.to_series().diff().iloc[1:] == HOUR).all()
    hours_since_pattern = (expanded.index - pattern.index[0]) // HOUR
    assert (expanded.to_numpy() == (hours_since_pattern % 24) * 60.0).all()
    # After the change, those values land half an hour off their local time.
    after = expanded[expanded.index >= pd.Timestamp("2026-04-06", tz=tz)]
    assert (after.index.minute == 30).all()


@pytest.mark.parametrize("tz", ["Asia/Kolkata", "UTC"])
def test_daily_repeat_without_dst(tz):
    """Without clock changes, wall-clock and absolute repetition agree, and nothing is reported."""
    pattern = minute_of_day_pattern(tz, "2026-03-27", DAY, QUARTER)

    expanded, report = expand_wall_clock_recurrence(
        pattern, date(2026, 3, 30), tz, QUARTER
    )

    assert len(expanded) == 3 * 96
    assert (expanded.to_numpy() == local_minute_of_day(expanded.index)).all()
    assert report.mode == "wall_clock"
    assert report.transitions == ()


def test_same_weekday_repeat():
    """Repeat a Sunday on the following Sundays only, across a spring-forward transition."""
    tz = "Europe/Amsterdam"
    pattern = minute_of_day_pattern(tz, "2026-03-22", DAY, HOUR)

    expanded, report = expand_wall_clock_recurrence(
        pattern, date(2026, 4, 5), tz, HOUR, same_weekday_only=True
    )

    assert report.period == "weekly"
    assert report.n_occurrences == 2
    with_values = expanded.dropna()
    assert set(with_values.index.date) == {date(2026, 3, 29), date(2026, 4, 5)}
    assert (with_values.index.dayofweek == 6).all()
    assert (with_values.to_numpy() == local_minute_of_day(with_values.index)).all()
    # The days in between are gaps in one contiguous series.
    assert expanded[str(date(2026, 4, 1))].isna().all()
    assert (expanded.index.to_series().diff().iloc[1:] == HOUR).all()
    (transition,) = report.transitions
    assert transition.omitted == (time(2, 0),)


def is_workday(day: date) -> bool:
    return day.weekday() < 5


def test_repeat_on_some_days_only():
    """Repeat a Friday on workdays only, which leaves the weekend of the fall-back transition as a gap."""
    tz = "Europe/Amsterdam"
    pattern = minute_of_day_pattern(tz, "2026-10-23", DAY, HOUR)  # a Friday

    expanded, report = expand_wall_clock_recurrence(
        pattern, date(2026, 10, 30), tz, HOUR, on_days=is_workday
    )

    assert report.n_occurrences == 5
    with_values = expanded.dropna()
    assert sorted(set(with_values.index.date)) == [
        date(2026, 10, d) for d in (26, 27, 28, 29, 30)
    ]
    assert (with_values.to_numpy() == local_minute_of_day(with_values.index)).all()
    # The weekend is a gap in one contiguous series, so its clock change writes nothing twice.
    assert expanded["2026-10-24":"2026-10-25"].isna().all()
    assert (expanded.index.to_series().diff().iloc[1:] == HOUR).all()
    assert sum(t.n_duplicated for t in report.transitions) == 0


def test_repeat_on_some_days_keeps_resolving_dst():
    """A day kept by the filter is still repeated by the wall clock, here writing the repeated hour twice."""
    tz = "Europe/Amsterdam"
    pattern = minute_of_day_pattern(tz, "2026-10-23", DAY, HOUR)

    expanded, report = expand_wall_clock_recurrence(
        pattern, date(2026, 10, 25), tz, HOUR, on_days=lambda day: day.weekday() >= 5
    )

    assert report.n_occurrences == 2
    assert sorted(set(expanded.dropna().index.date)) == [
        date(2026, 10, 24),
        date(2026, 10, 25),
    ]
    (transition,) = report.transitions
    assert transition.duplicated == (time(2, 0),)


def test_repeat_on_no_day_writes_nothing():
    tz = "Europe/Amsterdam"
    pattern = minute_of_day_pattern(tz, "2026-06-01", DAY, HOUR)

    expanded, report = expand_wall_clock_recurrence(
        pattern, date(2026, 6, 10), tz, HOUR, on_days=lambda day: False
    )

    assert expanded.empty
    assert report.n_occurrences == 0


def test_repeat_on_some_days_with_absolute_steps():
    """When repeats fall back to absolute steps, the filter still decides which repeats are written."""
    tz = "Australia/Lord_Howe"
    pattern = minute_of_day_pattern(tz, "2026-04-03", DAY, HOUR)  # a Friday

    expanded, report = expand_wall_clock_recurrence(
        pattern, date(2026, 4, 7), tz, HOUR, on_days=is_workday
    )

    assert report.mode == "absolute"
    assert report.n_occurrences == 2
    # Monday and Tuesday only, each 24 hours long, starting half an hour before local midnight after the clock change.
    starts = expanded.dropna().index
    assert len(starts) == 2 * 24
    assert starts[0] == pd.Timestamp("2026-04-05T23:30", tz=tz)
    assert expanded[: pd.Timestamp("2026-04-05T23:00", tz=tz)].isna().all()


@pytest.mark.parametrize(
    "same_weekday_only, duration, resolution, allowed",
    [
        (False, DAY, HOUR, True),
        (False, DAY + HOUR, HOUR, False),
        (True, 7 * DAY, HOUR, True),
        (True, 7 * DAY + HOUR, HOUR, False),
        # Instants a full period apart would land on the same instant once repeated.
        (False, DAY - HOUR, timedelta(0), True),
        (False, DAY + HOUR, timedelta(0), False),
    ],
)
def test_pattern_must_fit_the_recurrence_period(
    same_weekday_only, duration, resolution, allowed
):
    tz = "Europe/Amsterdam"
    if resolution:
        pattern = minute_of_day_pattern(tz, "2026-06-01", duration, resolution)
    else:
        pattern = pd.Series(
            [1.0, 2.0],
            index=pd.DatetimeIndex(
                [
                    pd.Timestamp("2026-06-01", tz=tz),
                    pd.Timestamp("2026-06-01", tz=tz) + duration,
                ]
            ),
        )
    if allowed:
        expand_wall_clock_recurrence(
            pattern, date(2026, 6, 30), tz, resolution, same_weekday_only
        )
    else:
        with pytest.raises(RecurrenceError, match="longer than the recurrence period"):
            expand_wall_clock_recurrence(
                pattern, date(2026, 6, 30), tz, resolution, same_weekday_only
            )


def test_pattern_span_is_measured_on_the_wall_clock():
    """A full local day on the day DST starts lasts 23 hours, and repeats as a full day."""
    tz = "Europe/Amsterdam"
    pattern = minute_of_day_pattern(tz, "2026-03-29", timedelta(hours=23), HOUR)

    expanded, _ = expand_wall_clock_recurrence(pattern, date(2026, 3, 30), tz, HOUR)

    # The source has no 02:00, so that slot stays empty in the repeat.
    assert len(expanded) == 24
    assert np.isnan(expanded[pd.Timestamp("2026-03-30 02:00", tz=tz)])
    assert expanded.count() == 23


def test_pattern_covering_a_repeated_hour_is_rejected():
    """On the day DST ends, two values claim the same local time, so the pattern cannot be repeated by wall clock."""
    tz = "Europe/Amsterdam"
    pattern = minute_of_day_pattern(tz, "2026-10-25", timedelta(hours=25), HOUR)

    with pytest.raises(RecurrenceError, match="fall-back"):
        expand_wall_clock_recurrence(pattern, date(2026, 10, 30), tz, HOUR)


@pytest.mark.parametrize(
    "until, exp_last",
    [
        (date(2026, 6, 3), "2026-06-03 23:00"),
        (date(2026, 6, 2), "2026-06-02 23:00"),
    ],
)
def test_until_is_inclusive(until, exp_last):
    tz = "Europe/Amsterdam"
    pattern = minute_of_day_pattern(tz, "2026-06-01", DAY, HOUR)

    expanded, report = expand_wall_clock_recurrence(pattern, until, tz, HOUR)

    assert expanded.index[0] == pd.Timestamp("2026-06-02 00:00", tz=tz)
    assert expanded.index[-1] == pd.Timestamp(exp_last, tz=tz)
    assert report.n_occurrences == (until - date(2026, 6, 1)).days


def test_until_cuts_off_a_repeat_running_into_the_next_day():
    """A pattern running past midnight is not written beyond the end of `until`."""
    tz = "Europe/Amsterdam"
    pattern = minute_of_day_pattern(tz, "2026-06-01 18:00", timedelta(hours=12), HOUR)

    expanded, report = expand_wall_clock_recurrence(pattern, date(2026, 6, 3), tz, HOUR)

    assert expanded.index[0] == pd.Timestamp("2026-06-02 18:00", tz=tz)
    assert expanded.index[-1] == pd.Timestamp("2026-06-03 23:00", tz=tz)
    assert report.n_occurrences == 2


def test_until_before_the_first_repeat_writes_nothing():
    tz = "Europe/Amsterdam"
    pattern = minute_of_day_pattern(tz, "2026-06-01", DAY, HOUR)

    expanded, report = expand_wall_clock_recurrence(pattern, date(2026, 6, 1), tz, HOUR)

    assert expanded.empty
    assert expanded.index.tz is not None
    assert report.n_occurrences == 0


def test_nan_stays_a_gap_and_is_not_reported():
    """A slot without a value stays empty in every repeat, and a clock change skipping or repeating it does not count it."""
    tz = "Europe/Amsterdam"
    pattern = minute_of_day_pattern(tz, "2026-03-27", DAY, HOUR)
    pattern[pattern.index.hour.isin([2, 7])] = np.nan

    expanded, report = expand_wall_clock_recurrence(
        pattern, date(2026, 3, 30), tz, HOUR
    )

    assert expanded[expanded.index.hour.isin([2, 7])].isna().all()
    assert expanded[~expanded.index.hour.isin([2, 7])].notna().all()
    (transition,) = report.transitions
    assert transition.kind == "spring_forward"
    assert transition.n_omitted == 0


def test_instantaneous_sensor():
    """Instants follow the same DST rules, and come back without a grid of gaps."""
    tz = "Europe/Amsterdam"
    pattern = pd.Series(
        [1.0, 2.0],
        index=pd.DatetimeIndex(
            [
                pd.Timestamp("2026-10-23 02:30", tz=tz),
                pd.Timestamp("2026-10-23 07:00", tz=tz),
            ]
        ),
    )

    expanded, report = expand_wall_clock_recurrence(
        pattern, date(2026, 10, 26), tz, timedelta(0)
    )

    assert list(expanded.index) == [
        pd.Timestamp("2026-10-24 02:30", tz=tz),
        pd.Timestamp("2026-10-24 07:00", tz=tz),
        pd.Timestamp("2026-10-25 02:30+02:00"),
        pd.Timestamp("2026-10-25 02:30+01:00"),
        pd.Timestamp("2026-10-25 07:00", tz=tz),
        pd.Timestamp("2026-10-26 02:30", tz=tz),
        pd.Timestamp("2026-10-26 07:00", tz=tz),
    ]
    assert list(expanded) == [1.0, 2.0, 1.0, 1.0, 2.0, 1.0, 2.0]
    (transition,) = report.transitions
    assert transition.duplicated == (time(2, 30),)


def test_daily_resolution_stays_on_local_midnight():
    """Slots of a day are calendar days, so they keep following local midnight across a clock change."""
    tz = "Europe/Amsterdam"
    pattern = pd.Series(
        [10.0, 20.0],
        index=pd.DatetimeIndex(
            [pd.Timestamp("2026-03-23", tz=tz), pd.Timestamp("2026-03-24", tz=tz)]
        ),
    )

    expanded, report = expand_wall_clock_recurrence(
        pattern, date(2026, 4, 6), tz, DAY, same_weekday_only=True
    )

    assert report.mode == "wall_clock"
    assert (expanded.index.hour == 0).all()
    assert expanded[pd.Timestamp("2026-03-30", tz=tz)] == 10.0
    assert expanded[pd.Timestamp("2026-03-31", tz=tz)] == 20.0
    assert expanded[pd.Timestamp("2026-04-06", tz=tz)] == 10.0


@pytest.mark.parametrize(
    "pattern_kwargs, args, match",
    [
        (dict(tz=None), dict(), "timezone-aware"),
        (dict(), dict(tz="Mars/Olympus_Mons"), "Unknown timezone"),
        (dict(), dict(resolution=timedelta(hours=7)), "whole number of times"),
        (dict(), dict(resolution=QUARTER), "regular"),
    ],
)
def test_invalid_input_is_rejected(pattern_kwargs, args, match):
    tz = pattern_kwargs.get("tz", "Europe/Amsterdam")
    pattern = pd.Series(
        [1.0, 2.0], index=pd.date_range("2026-06-01", periods=2, freq="1h", tz=tz)
    )
    kwargs = dict(until=date(2026, 6, 3), tz="Europe/Amsterdam", resolution=HOUR)
    kwargs.update(args)

    with pytest.raises(RecurrenceError, match=match):
        expand_wall_clock_recurrence(pattern, **kwargs)


def test_report_is_json_serializable():
    tz = "Europe/Amsterdam"
    pattern = minute_of_day_pattern(tz, "2026-10-23", DAY, QUARTER)

    _, report = expand_wall_clock_recurrence(pattern, date(2026, 10, 26), tz, QUARTER)

    described = json.loads(json.dumps(report.to_dict()))
    assert described["transitions"] == [
        {
            "date": "2026-10-25",
            "kind": "fall_back",
            "shift": "PT1H",
            "wall_clock_start": "02:00",
            "wall_clock_end": "03:00",
            "omitted": [],
            "duplicated": ["02:00", "02:15", "02:30", "02:45"],
            "n_omitted": 0,
            "n_duplicated": 4,
        }
    ]
