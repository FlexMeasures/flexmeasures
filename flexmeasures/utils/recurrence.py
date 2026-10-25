"""Utility module for repeating a pattern of sensor values by local wall-clock time.

A pattern is a short stretch of values, such as one day of SoC limits,
which is repeated daily (or weekly, to keep only the same weekday) until a given date.
The values encode human intentions ("80% by 07:00"),
so each repeat lands on the same local time-of-day, rather than a fixed 24 hours later.

Daylight saving time transitions are resolved here, once, by an explicit policy:
by default, slots whose local time does not exist (spring forward) are omitted,
and slots whose local time occurs twice (fall back) are written to both instants.
The report returned alongside the values says which slots that concerned, so they can be previewed.

This module is pure: it depends on neither Flask, the database nor the UI.
See https://github.com/FlexMeasures/flexmeasures/issues/2255 for the design discussion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Callable, Literal
from zoneinfo import ZoneInfoNotFoundError

import isodate
import numpy as np
import pandas as pd
from pytz.exceptions import UnknownTimeZoneError


class RecurrenceError(ValueError):
    """Raised when a pattern cannot be repeated as asked."""


class NonexistentTime(Enum):
    """What to do with a slot whose local time is skipped by a spring-forward transition."""

    #: Omit the slot, as RFC 5545 does for nonexistent recurrence times.
    DROP = "drop"


class AmbiguousTime(Enum):
    """What to do with a slot whose local time occurs twice in a fall-back transition."""

    #: Write the value to both instants, which is the safe reading for a limit.
    BOTH = "both"


@dataclass(frozen=True)
class DstPolicy:
    """How to resolve daylight saving time transitions when repeating by wall-clock time.

    The two kinds of transition are resolved independently,
    so that alternatives (such as shifting into the adjacent hour, or writing only the first occurrence) can be added to either one later.
    """

    nonexistent: NonexistentTime = NonexistentTime.DROP
    ambiguous: AmbiguousTime = AmbiguousTime.BOTH


@dataclass(frozen=True)
class DstTransition:
    """One clock change within the range being written, and the slots it affected.

    Slots are given as local wall-clock times on the date of the transition,
    because an omitted slot has no instant to give.
    Slots without a value (NaN in the pattern) are not counted as affected.
    """

    date: date
    kind: Literal["spring_forward", "fall_back"]
    #: The size of the clock change, such as 1 hour, or 30 minutes on Lord Howe Island.
    shift: timedelta
    #: The local wall-clock times that are skipped (spring forward) or that occur twice (fall back).
    wall_clock_start: time
    wall_clock_end: time
    omitted: tuple[time, ...] = ()
    duplicated: tuple[time, ...] = ()

    @property
    def n_omitted(self) -> int:
        """Count the slots not written, because their local time does not exist."""
        return len(self.omitted)

    @property
    def n_duplicated(self) -> int:
        """Count the slots written to both instants of their ambiguous local time."""
        return len(self.duplicated)

    def to_dict(self) -> dict:
        """Describe the transition in JSON-serializable terms."""
        return dict(
            date=self.date.isoformat(),
            kind=self.kind,
            shift=isodate.duration_isoformat(self.shift),
            wall_clock_start=self.wall_clock_start.isoformat(timespec="minutes"),
            wall_clock_end=self.wall_clock_end.isoformat(timespec="minutes"),
            omitted=[t.isoformat(timespec="minutes") for t in self.omitted],
            duplicated=[t.isoformat(timespec="minutes") for t in self.duplicated],
            n_omitted=self.n_omitted,
            n_duplicated=self.n_duplicated,
        )


@dataclass(frozen=True)
class RecurrenceReport:
    """What the expansion did, for previewing it before anything is written."""

    #: "wall_clock" normally, or "absolute" when the sensor resolution cannot follow a clock change.
    mode: Literal["wall_clock", "absolute"]
    period: Literal["daily", "weekly"]
    #: The number of repeats, not counting the pattern itself.
    n_occurrences: int
    transitions: tuple[DstTransition, ...] = field(default_factory=tuple)
    #: Why the expansion fell back to absolute repetition, if it did.
    fallback_reason: str | None = None

    def to_dict(self) -> dict:
        """Describe the report in JSON-serializable terms."""
        return dict(
            mode=self.mode,
            period=self.period,
            n_occurrences=self.n_occurrences,
            transitions=[t.to_dict() for t in self.transitions],
            fallback_reason=self.fallback_reason,
        )


def expand_wall_clock_recurrence(
    pattern: pd.Series,
    until: date,
    tz: str,
    resolution: timedelta,
    same_weekday_only: bool = False,
    policy: DstPolicy = DstPolicy(),
    on_days: Callable[[date], bool] | None = None,
) -> tuple[pd.Series, RecurrenceReport]:
    """Repeat a pattern of sensor values daily (or weekly) by local wall-clock time, until a given date.

    Each source slot is mapped by its local time-of-day, so a value at 07:00 lands at 07:00 on every repeat, also across a DST transition.
    The first repeat directly follows the pattern (one day or one week later), and the pattern itself is not returned.
    Repeating stops at the end of `until`: a slot is written only if it starts before the local midnight that follows it,
    so the last repeat is cut short there if it would run into the next day.

    For a sensor with a resolution, the result is one contiguous series at that resolution,
    from the first slot written to the last, so it can be sent as one array of values.
    Where there is no value to write (a NaN in the pattern, a gap between repeats, or an omitted slot), the result holds NaN.
    For an instantaneous sensor (a zero resolution), the result holds only the repeated instants.

    If the resolution does not divide the size of a clock change in the range written (such as hourly data on Lord Howe Island, whose clocks shift by 30 minutes),
    following the wall clock would break the sensor's grid of events,
    so the pattern is repeated by absolute steps of 24 hours (or 168 hours) instead, and the report says so.
    That fallback never applies to resolutions of a day or more, whose slots are calendar days.

    :param pattern:             Values with a timezone-aware index, regular at the sensor resolution; NaN means "no value".
    :param until:               The last local date (in `tz`) to write values on, inclusive.
    :param tz:                  The sensor's timezone, as an IANA name, such as "Europe/Amsterdam".
    :param resolution:          The sensor's event resolution, or zero for an instantaneous sensor.
    :param same_weekday_only:   Repeat every 7 days instead of every day.
    :param policy:              How to resolve DST transitions.
    :param on_days:             Only repeat on the local dates for which this returns True, such as workdays,
                                where a repeat's date is the date its first slot falls on.
    :returns:                   The repeated values, indexed in `tz`, and a report of what DST transitions did to them.
    :raises RecurrenceError:    When the pattern is longer than the recurrence period, is not regular at the resolution,
                                or covers the repeated hour of a fall-back transition (two values would claim the same wall-clock time).
    """
    period = timedelta(days=7 if same_weekday_only else 1)
    period_name: Literal["daily", "weekly"] = "weekly" if same_weekday_only else "daily"
    resolution = pd.Timedelta(resolution).to_pytimedelta()
    _validate_inputs(pattern, until, tz, resolution, period)

    local_index = pattern.index.tz_convert(tz)
    # Naive local wall-clock times, on purpose: this is the frame in which the pattern repeats.
    wall_clock = local_index.tz_localize(None)
    _validate_wall_clock_span(wall_clock, resolution, period)

    end_of_until = pd.Timestamp(until + timedelta(days=1))  # naive local midnight
    n_occurrences = max(
        0, int(np.ceil((end_of_until - wall_clock[0]) / pd.Timedelta(period))) - 1
    )
    # Which repeats to write, by the local date each starts on.
    first_day = wall_clock[0].date()
    kept_occurrences = np.array(
        [
            on_days is None or on_days(first_day + k * period)
            for k in range(1, n_occurrences + 1)
        ],
        dtype=bool,
    )
    if n_occurrences == 0 or not kept_occurrences.any():
        empty = pd.Series(
            [], index=pd.DatetimeIndex([], tz=tz), dtype=float, name=pattern.name
        )
        return empty, RecurrenceReport(
            mode="wall_clock", period=period_name, n_occurrences=0
        )

    end_instant = end_of_until.tz_localize(
        tz, ambiguous=True, nonexistent="shift_forward"
    )
    transitions = _clock_changes(tz, local_index[0], end_instant)
    pattern_end = local_index[-1] + resolution
    written_transitions = [t for t in transitions if t[0] >= pattern_end]

    # Wall-clock repeats stay on the sensor's grid only if the resolution divides every clock change they cross.
    # Slots of a day or more are calendar days, which follow the wall clock whatever the size of the change.
    incompatible = [
        abs(after - before)
        for _, before, after in transitions
        if timedelta(0) < resolution < timedelta(days=1)
        and abs(after - before) % resolution != timedelta(0)
    ]
    if incompatible:
        expanded = _expand_absolute(
            pattern,
            local_index,
            kept_occurrences,
            period,
            resolution,
            end_instant,
            tz,
        )
        report = RecurrenceReport(
            mode="absolute",
            period=period_name,
            n_occurrences=int(kept_occurrences.sum()),
            transitions=tuple(
                _describe(t, omitted=[], duplicated=[]) for t in written_transitions
            ),
            fallback_reason=(
                f"The sensor resolution ({isodate.duration_isoformat(resolution)}) does not divide a clock change of "
                f"{isodate.duration_isoformat(incompatible[0])} in {tz}, "
                f"so values are repeated every {int(period / timedelta(hours=1))} hours instead of at the same local time."
            ),
        )
        return expanded, report

    expanded, omitted, duplicated = _expand_wall_clock(
        pattern,
        wall_clock,
        kept_occurrences,
        period,
        resolution,
        end_of_until,
        tz,
        policy,
    )
    report = RecurrenceReport(
        mode="wall_clock",
        period=period_name,
        n_occurrences=int(kept_occurrences.sum()),
        transitions=tuple(
            _describe(t, omitted=omitted, duplicated=duplicated)
            for t in written_transitions
        ),
    )
    return expanded, report


def _validate_inputs(
    pattern: pd.Series,
    until: date,
    tz: str,
    resolution: timedelta,
    period: timedelta,
):
    """Check that the inputs describe a pattern that can be repeated at all."""
    if not isinstance(pattern.index, pd.DatetimeIndex) or pattern.index.tz is None:
        raise RecurrenceError(
            "The pattern must be indexed by timezone-aware datetimes."
        )
    if pattern.empty:
        raise RecurrenceError("The pattern holds no slots to repeat.")
    if isinstance(until, datetime) or not isinstance(until, date):
        raise RecurrenceError(
            f"Repeat until a date, not {until!r}, as it is read in the sensor's timezone."
        )
    try:
        pd.Timestamp(0, tz="UTC").tz_convert(tz)
    except (UnknownTimeZoneError, ZoneInfoNotFoundError) as exc:
        # Which of the two is raised depends on whether pandas is backed by pytz or zoneinfo.
        raise RecurrenceError(f"Unknown timezone {tz!r}.") from exc
    if resolution < timedelta(0):
        raise RecurrenceError("The resolution must not be negative.")
    if resolution > timedelta(0) and (
        period % resolution != timedelta(0)
        or (
            resolution >= timedelta(days=1)
            and resolution % timedelta(days=1) != timedelta(0)
        )
    ):
        raise RecurrenceError(
            f"A resolution of {isodate.duration_isoformat(resolution)} does not fit a whole number of times in the recurrence period of "
            f"{isodate.duration_isoformat(period)}, so repeats would fall off the sensor's grid of events."
        )
    if not pattern.index.is_monotonic_increasing or not pattern.index.is_unique:
        raise RecurrenceError(
            "The pattern must be sorted in time, without duplicate slots."
        )
    if resolution > timedelta(0) and len(pattern) > 1:
        if resolution < timedelta(days=1):
            steps = pattern.index.to_series().diff().iloc[1:]
        else:
            # Slots of a day or more are calendar days, so step through them on the wall clock.
            steps = (
                pattern.index.tz_convert(tz)
                .tz_localize(None)
                .to_series()
                .diff()
                .iloc[1:]
            )
        if not (steps == resolution).all():
            raise RecurrenceError(
                f"The pattern must be regular, at the sensor resolution of {isodate.duration_isoformat(resolution)}."
            )


def _validate_wall_clock_span(
    wall_clock: pd.DatetimeIndex, resolution: timedelta, period: timedelta
):
    """Check that no two source slots claim the same local time-of-day once repeated."""
    if not wall_clock.is_unique:
        raise RecurrenceError(
            "The pattern covers the repeated hour of a fall-back transition, "
            "so two of its values claim the same local time; select a pattern that leaves out one of the two."
        )
    if resolution > timedelta(0):
        span = wall_clock[-1] + resolution - wall_clock[0]
        too_long = span > period
    else:
        # Two instants exactly one period apart would land on the same instant once repeated.
        span = wall_clock[-1] - wall_clock[0]
        too_long = span >= period
    if too_long:
        raise RecurrenceError(
            f"The pattern spans {isodate.duration_isoformat(span.to_pytimedelta())} of local time, "
            f"which is longer than the recurrence period of {isodate.duration_isoformat(period)}, "
            "so repeats would overlap; select a shorter pattern, or repeat on the same weekday only."
        )


def _expand_wall_clock(
    pattern: pd.Series,
    wall_clock: pd.DatetimeIndex,
    kept_occurrences: np.ndarray,
    period: timedelta,
    resolution: timedelta,
    end_of_until: pd.Timestamp,
    tz: str,
    policy: DstPolicy,
) -> tuple[pd.Series, list[pd.Timestamp], list[pd.Timestamp]]:
    """Repeat the pattern on the wall clock, and localize each repeat in the sensor's timezone.

    Returns the expanded series, and the naive local times of the slots with a value that were omitted or duplicated.
    """
    # Repeats are stepped on naive local times, where adding whole days always keeps the time-of-day.
    # Don't step tz-aware times instead: freq="24h", pd.Timedelta("1D") and pd.offsets.Day(1) are absolute (Day is a Tick offset, despite its name, at least before pandas 3),
    # and even a calendar-aware pd.DateOffset(days=1) can only land on one of the two instants of an ambiguous local time, where we may want both.
    n_occurrences = len(kept_occurrences)
    steps = pd.TimedeltaIndex(np.arange(1, n_occurrences + 1) * pd.Timedelta(period))
    targets = pd.DatetimeIndex(
        (wall_clock.values[None, :] + steps.values[:, None]).ravel()
    )
    values = np.tile(pattern.to_numpy(dtype=float), n_occurrences)
    keep = (targets < end_of_until) & np.repeat(kept_occurrences, len(pattern))
    repeated = pd.Series(values[keep], index=targets[keep])

    if resolution > timedelta(0):
        # Lay the values on a contiguous wall-clock grid, so the gaps between repeats show as NaN.
        # Given the resolution divides any clock change (checked by the caller), localizing this grid gives the sensor's own grid of events.
        grid = pd.date_range(repeated.index[0], repeated.index[-1], freq=resolution)
        repeated = repeated.reindex(grid)

    # Localize twice: once reading ambiguous times as the first instant (DST), once as the second.
    # Times that exist once come out the same both ways, and nonexistent times come out as NaT.
    first = repeated.index.tz_localize(
        tz, ambiguous=np.ones(len(repeated), dtype=bool), nonexistent="NaT"
    )
    second = repeated.index.tz_localize(
        tz, ambiguous=np.zeros(len(repeated), dtype=bool), nonexistent="NaT"
    )
    nonexistent = first.isna()
    ambiguous = ~nonexistent & (first != second)
    has_value = repeated.notna().to_numpy()

    if policy.nonexistent is NonexistentTime.DROP:
        kept = ~nonexistent
    else:
        raise NotImplementedError(f"DST policy {policy.nonexistent} is not supported.")
    if policy.ambiguous is AmbiguousTime.BOTH:
        index = first[kept].append(second[ambiguous])
        expanded_values = np.concatenate(
            [repeated.to_numpy()[kept], repeated.to_numpy()[ambiguous]]
        )
    else:
        raise NotImplementedError(f"DST policy {policy.ambiguous} is not supported.")
    expanded = pd.Series(expanded_values, index=index, name=pattern.name).sort_index()

    omitted = list(repeated.index[nonexistent & has_value])
    duplicated = list(repeated.index[ambiguous & has_value])
    return expanded, omitted, duplicated


def _expand_absolute(
    pattern: pd.Series,
    local_index: pd.DatetimeIndex,
    kept_occurrences: np.ndarray,
    period: timedelta,
    resolution: timedelta,
    end_instant: pd.Timestamp,
    tz: str,
) -> pd.Series:
    """Repeat the pattern by absolute steps of the period, keeping the sensor's grid of events intact."""
    # Absolute on purpose: tz-aware times plus a Timedelta keep their distance in hours, not their time-of-day.
    n_occurrences = len(kept_occurrences)
    steps = pd.TimedeltaIndex(np.arange(1, n_occurrences + 1) * pd.Timedelta(period))
    targets = pd.DatetimeIndex(
        (
            local_index.tz_convert("UTC").tz_localize(None).values[None, :]
            + steps.values[:, None]
        ).ravel()
    ).tz_localize("UTC")
    values = np.tile(pattern.to_numpy(dtype=float), n_occurrences)
    keep = (targets < end_instant) & np.repeat(kept_occurrences, len(pattern))
    repeated = pd.Series(
        values[keep], index=targets[keep].tz_convert(tz), name=pattern.name
    )
    if repeated.empty:
        return repeated
    grid = pd.date_range(repeated.index[0], repeated.index[-1], freq=resolution)
    return repeated.reindex(grid)


def _clock_changes(
    tz: str, start: pd.Timestamp, end: pd.Timestamp
) -> list[tuple[pd.Timestamp, timedelta, timedelta]]:
    """List the instants in [start, end) at which the UTC offset of `tz` changes, with the offsets before and after."""
    hours = pd.date_range(
        start.tz_convert("UTC").floor("h"), end.tz_convert("UTC").ceil("h"), freq="h"
    )
    offsets = _utc_offsets(hours, tz)
    changes = []
    for i in np.flatnonzero(offsets[1:] != offsets[:-1]):
        # Clocks change on whole minutes, so find the exact minute within the hour.
        minutes = pd.date_range(hours[i], hours[i + 1], freq="min")
        minute_offsets = _utc_offsets(minutes, tz)
        instant = minutes[np.argmax(minute_offsets != offsets[i])]
        if start <= instant < end:
            changes.append(
                (
                    instant.tz_convert(tz),
                    offsets[i].to_pytimedelta(),
                    offsets[i + 1].to_pytimedelta(),
                )
            )
    return changes


def _utc_offsets(instants: pd.DatetimeIndex, tz: str) -> pd.TimedeltaIndex:
    """Compute the UTC offset of `tz` at each of the given instants."""
    return instants.tz_convert(tz).tz_localize(None) - instants.tz_convert(
        "UTC"
    ).tz_localize(None)


def _describe(
    change: tuple[pd.Timestamp, timedelta, timedelta],
    omitted: list[pd.Timestamp],
    duplicated: list[pd.Timestamp],
) -> DstTransition:
    """Describe one clock change, with the omitted and duplicated slots that fall within it."""
    instant, before, after = change
    naive_instant = instant.tz_convert("UTC").tz_localize(None)
    # The wall-clock window that is skipped (spring forward) or that occurs twice (fall back).
    window_start = naive_instant + min(before, after)
    window_end = naive_instant + max(before, after)
    in_window = [
        t
        for t in (omitted if after > before else duplicated)
        if window_start <= t < window_end
    ]
    slots = tuple(t.time() for t in in_window)
    return DstTransition(
        date=(naive_instant + before).date(),
        kind="spring_forward" if after > before else "fall_back",
        shift=abs(after - before),
        wall_clock_start=window_start.time(),
        wall_clock_end=window_end.time(),
        omitted=slots if after > before else (),
        duplicated=slots if after < before else (),
    )
