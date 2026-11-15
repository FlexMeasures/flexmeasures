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
            "spring-forward",
            HOUR,
            [time(2, 0), time(2, 15), time(2, 30), time(2, 45)],
            [],
        ),
        (
            "Europe/Amsterdam",
            QUARTER,
            date(2026, 10, 25),
            "fall-back",
            HOUR,
            [],
            [time(2, 0), time(2, 15), time(2, 30), time(2, 45)],
        ),
        # Southern hemisphere: the same months, in the opposite direction.
        (
            "Australia/Sydney",
            QUARTER,
            date(2026, 4, 5),
            "fall-back",
            HOUR,
            [],
            [time(2, 0), time(2, 15), time(2, 30), time(2, 45)],
        ),
        (
            "Australia/Sydney",
            HOUR,
            date(2026, 10, 4),
            "spring-forward",
            HOUR,
            [time(2, 0)],
            [],
        ),
        # Lord Howe Island shifts its clocks by 30 minutes, which a 15-minute resolution can follow.
        (
            "Australia/Lord_Howe",
            QUARTER,
            date(2026, 4, 5),
            "fall-back",
            timedelta(minutes=30),
            [],
            [time(1, 30), time(1, 45)],
        ),
        (
            "Australia/Lord_Howe",
            QUARTER,
            date(2026, 10, 4),
            "spring-forward",
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

    assert report.n_occurrences == 3
    assert report.n_transitions_checked == 1
    (transition,) = report.transitions
    assert transition.date == transition_date
    assert transition.kind == kind
    assert transition.shift == shift
    assert list(transition.omitted) == exp_omitted
    assert list(transition.duplicated) == exp_duplicated
    assert transition.n_omitted == len(exp_omitted)
    assert transition.n_duplicated == len(exp_duplicated)


@pytest.mark.parametrize(
    "tz, pattern_day, until, resolution, exp_starts, exp_kind, exp_effect",
    [
        # Lord Howe Island turns its clock back 30 minutes at 02:00, so 01:30-02:00 runs twice:
        # an extra hour of the 01:00 value fills it, starting half an hour before the second run, so 02:00 still starts on the hour.
        (
            "Australia/Lord_Howe",
            "2026-04-03",
            date(2026, 4, 6),
            HOUR,
            [
                ("2026-04-05T00:00+11:00", 0),
                ("2026-04-05T01:00+11:00", 60),
                ("2026-04-05T01:30+11:00", 60),
                ("2026-04-05T02:00+10:30", 120),
                ("2026-04-05T03:00+10:30", 180),
            ],
            "fall-back",
            dict(duplicated=(time(1, 0),)),
        ),
        # Lord Howe Island skips 02:00-02:30: the 02:00 slot starts when the clock resumes, at 02:30.
        (
            "Australia/Lord_Howe",
            "2026-10-02",
            date(2026, 10, 5),
            HOUR,
            [
                ("2026-10-04T00:00+10:30", 0),
                ("2026-10-04T01:00+10:30", 60),
                ("2026-10-04T02:30+11:00", 120),
                ("2026-10-04T03:00+11:00", 180),
                ("2026-10-04T04:00+11:00", 240),
            ],
            "spring-forward",
            dict(shifted=(time(2, 0),)),
        ),
        # Two-hourly slots on odd hours: no slot starts in the repeated hour, so the 01:00 slot fills it.
        (
            "Europe/Amsterdam",
            "2026-10-23 01:00",
            date(2026, 10, 26),
            2 * HOUR,
            [
                ("2026-10-25T01:00+02:00", 60),
                ("2026-10-25T02:00+02:00", 60),
                ("2026-10-25T03:00+01:00", 180),
                ("2026-10-25T05:00+01:00", 300),
            ],
            "fall-back",
            dict(duplicated=(time(1, 0),)),
        ),
        # Two-hourly slots on even hours: the 02:00 slot loses its first hour, and starts at 03:00.
        (
            "Europe/Amsterdam",
            "2026-03-27",
            date(2026, 3, 30),
            2 * HOUR,
            [
                ("2026-03-29T00:00+01:00", 0),
                ("2026-03-29T03:00+02:00", 120),
                ("2026-03-29T04:00+02:00", 240),
            ],
            "spring-forward",
            dict(shifted=(time(2, 0),)),
        ),
        # A day that starts with a skipped midnight still gets its value, from 01:00.
        (
            "America/Santiago",
            "2026-09-05",
            date(2026, 9, 7),
            DAY,
            [
                ("2026-09-06T01:00-03:00", 0),
                ("2026-09-07T00:00-03:00", 0),
            ],
            "spring-forward",
            dict(shifted=(time(0, 0),)),
        ),
    ],
)
def test_repeats_stay_on_local_time_if_the_resolution_is_coarser_than_the_clock_change(
    tz, pattern_day, until, resolution, exp_starts, exp_kind, exp_effect
):
    """Without an absolute fallback, slots keep their local start time, and the clock change is absorbed by one extra or moved event."""
    if resolution == DAY:
        # One calendar day, built directly, as the day after it starts with a skipped midnight.
        pattern = pd.Series([0.0], index=[pd.Timestamp(pattern_day, tz=tz)])
    else:
        pattern = minute_of_day_pattern(tz, pattern_day, DAY, resolution)

    expanded, report = expand_wall_clock_recurrence(pattern, until, tz, resolution)

    transition_day = pd.Timestamp(exp_starts[0][0]).date()
    for start, value in exp_starts:
        assert expanded[pd.Timestamp(start)] == value, start
    # Every listed event is consecutive, so nothing else was written in between.
    on_day = expanded[
        (expanded.index >= pd.Timestamp(exp_starts[0][0]))
        & (expanded.index <= pd.Timestamp(exp_starts[-1][0]))
    ]
    assert len(on_day) == len(exp_starts)
    (transition,) = report.transitions
    assert transition.date == transition_day
    assert transition.kind == exp_kind
    for effect in ("omitted", "duplicated", "shifted"):
        assert getattr(transition, effect) == exp_effect.get(effect, ())


def test_fill_leaves_no_gap_in_absolute_time():
    """Around Lord Howe Island's fall-back, hourly events cover every instant, overlapping by half an hour."""
    tz = "Australia/Lord_Howe"
    pattern = minute_of_day_pattern(tz, "2026-04-03", DAY, HOUR)

    expanded, _ = expand_wall_clock_recurrence(pattern, date(2026, 4, 6), tz, HOUR)

    starts = expanded.index.tz_convert("UTC")
    assert (starts.to_series().diff().iloc[1:] <= HOUR).all()


@pytest.mark.parametrize("tz", ["Asia/Kolkata", "UTC"])
def test_daily_repeat_without_dst(tz):
    """Without clock changes, wall-clock and absolute repetition agree, and nothing is reported."""
    pattern = minute_of_day_pattern(tz, "2026-03-27", DAY, QUARTER)

    expanded, report = expand_wall_clock_recurrence(
        pattern, date(2026, 3, 30), tz, QUARTER
    )

    assert len(expanded) == 3 * 96
    assert (expanded.to_numpy() == local_minute_of_day(expanded.index)).all()
    assert report.n_transitions_checked == 0
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
    # The clock change was checked, but is not listed, as it affected no value.
    assert report.n_transitions_checked == 1
    assert report.transitions == ()


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


@pytest.mark.parametrize(
    "pattern_day, on_days, exp_included, exp_first",
    [
        ("2026-10-23", None, True, "2026-10-23"),  # a Friday, repeated daily
        ("2026-10-23", is_workday, True, "2026-10-23"),
        # A Saturday pattern repeated on workdays is left out, so the first value is on Monday.
        ("2026-10-24", is_workday, False, "2026-10-26"),
    ],
)
def test_include_pattern(pattern_day, on_days, exp_included, exp_first):
    """The pattern itself is returned too, unless the repeat days leave out its own day."""
    tz = "Europe/Amsterdam"
    pattern = minute_of_day_pattern(tz, pattern_day, DAY, HOUR)

    expanded, report = expand_wall_clock_recurrence(
        pattern, date(2026, 10, 30), tz, HOUR, on_days=on_days, include_pattern=True
    )

    assert report.pattern_included is exp_included
    assert expanded.dropna().index[0] == pd.Timestamp(exp_first, tz=tz)
    if exp_included:
        assert (expanded[: pattern.index[-1]] == pattern).all()
    # The pattern is not counted as a repeat.
    without_pattern, _ = expand_wall_clock_recurrence(
        pattern, date(2026, 10, 30), tz, HOUR, on_days=on_days
    )
    assert report.n_occurrences == _.n_occurrences
    assert without_pattern.index[0] > pattern.index[-1]


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


@pytest.mark.parametrize("include_pattern", [False, True])
def test_until_before_the_pattern_writes_nothing(include_pattern):
    tz = "Europe/Amsterdam"
    pattern = minute_of_day_pattern(tz, "2026-06-01", DAY, HOUR)

    expanded, report = expand_wall_clock_recurrence(
        pattern, date(2026, 5, 31), tz, HOUR, include_pattern=include_pattern
    )

    assert expanded.empty
    assert report.pattern_included is False


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
    assert report.n_transitions_checked == 1
    assert report.transitions == ()


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
    assert described["n-transitions-checked"] == 1
    assert described["n-duplicated"] == 4
    assert described["transitions"] == [
        {
            "date": "2026-10-25",
            "kind": "fall-back",
            "shift": "PT1H",
            "wall-clock-start": "02:00",
            "wall-clock-end": "03:00",
            "omitted": [],
            "duplicated": ["02:00", "02:15", "02:30", "02:45"],
            "shifted": [],
            "n-omitted": 0,
            "n-duplicated": 4,
            "n-shifted": 0,
        }
    ]
