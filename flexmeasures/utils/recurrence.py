"""Utility module for repeating a pattern of sensor values by local wall-clock time.

A pattern is a short stretch of values, such as one day of SoC limits,
which is repeated daily (or weekly, to keep only the same weekday) until a given date.
The values encode human intentions ("80% by 07:00"),
so each repeat lands on the same local time-of-day, rather than a fixed 24 hours later.

Daylight saving time transitions are resolved here, once, by an explicit policy:
by default, slots whose local time does not exist (spring forward) are omitted,
and slots whose local time occurs twice (fall back) are written to both instants.
Where the sensor resolution is coarser than the clock change (such as hourly data on Lord Howe Island, whose clocks shift by 30 minutes),
repeats still start on the local time of their slot:
a slot only partly skipped by the clock starts when the clock resumes,
and the repeated part of the clock is filled from the slot that precedes it, as an extra event.
Such events may overlap their neighbours, which is fine for limits.
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

    #: Omit the slot if the clock skips all of it, as RFC 5545 does for nonexistent recurrence times,
    #: and start it when the clock resumes if the clock skips only its beginning.
    DROP = "drop"


class AmbiguousTime(Enum):
    """What to do with a slot whose local time occurs twice in a fall-back transition."""

    #: Write the value to both instants, which is the safe reading for a limit,
    #: and fill any part of the repeated clock that no slot starts in from the slot that precedes it.
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

    Slots are given as their local wall-clock start times,
    because an omitted slot has no instant to give.
    Slots without a value (NaN in the pattern) are not counted as affected.
    """

    date: date
    kind: Literal["spring-forward", "fall-back"]
    #: The size of the clock change, such as 1 hour, or 30 minutes on Lord Howe Island.
    shift: timedelta
    #: The local wall-clock times that are skipped (spring forward) or that occur twice (fall back).
    wall_clock_start: time
    wall_clock_end: time
    #: Slots not written, because the clock skips all of them.
    omitted: tuple[time, ...] = ()
    #: Slots written twice: to both instants of their local time,
    #: or once more as an extra event filling the repeated part of the clock that no slot starts in.
    duplicated: tuple[time, ...] = ()
    #: Slots whose start is skipped but whose end is not, which start when the clock resumes instead.
    shifted: tuple[time, ...] = ()

    @property
    def n_omitted(self) -> int:
        """Count the slots not written, because their local time does not exist."""
        return len(self.omitted)

    @property
    def n_duplicated(self) -> int:
        """Count the slots written twice around a fall-back transition."""
        return len(self.duplicated)

    @property
    def n_shifted(self) -> int:
        """Count the slots that start when the clock resumes, rather than at their own local time."""
        return len(self.shifted)

    @property
    def has_effect(self) -> bool:
        """Tell whether the clock change left out, repeated or moved any value."""
        return bool(self.n_omitted or self.n_duplicated or self.n_shifted)

    def to_dict(self) -> dict:
        """Describe the transition in JSON-serializable terms."""
        return {
            "date": self.date.isoformat(),
            "kind": self.kind,
            "shift": isodate.duration_isoformat(self.shift),
            "wall-clock-start": self.wall_clock_start.isoformat(timespec="minutes"),
            "wall-clock-end": self.wall_clock_end.isoformat(timespec="minutes"),
            "omitted": [t.isoformat(timespec="minutes") for t in self.omitted],
            "duplicated": [t.isoformat(timespec="minutes") for t in self.duplicated],
            "shifted": [t.isoformat(timespec="minutes") for t in self.shifted],
            "n-omitted": self.n_omitted,
            "n-duplicated": self.n_duplicated,
            "n-shifted": self.n_shifted,
        }


@dataclass(frozen=True)
class RecurrenceReport:
    """What the expansion did, for previewing it before anything is written."""

    period: Literal["daily", "weekly"]
    #: The number of repeats, not counting the pattern itself.
    n_occurrences: int
    #: Whether the pattern itself is part of the result.
    pattern_included: bool = False
    #: The number of clock changes within the range written, whether or not they affected any value.
    n_transitions_checked: int = 0
    #: The clock changes that left out, repeated or moved a value.
    transitions: tuple[DstTransition, ...] = field(default_factory=tuple)

    @property
    def n_omitted(self) -> int:
        return sum(t.n_omitted for t in self.transitions)

    @property
    def n_duplicated(self) -> int:
        return sum(t.n_duplicated for t in self.transitions)

    @property
    def n_shifted(self) -> int:
        return sum(t.n_shifted for t in self.transitions)

    def to_dict(self) -> dict:
        """Describe the report in JSON-serializable terms."""
        return {
            "period": self.period,
            "n-occurrences": self.n_occurrences,
            "pattern-included": self.pattern_included,
            "n-omitted": self.n_omitted,
            "n-duplicated": self.n_duplicated,
            "n-shifted": self.n_shifted,
            "n-transitions-checked": self.n_transitions_checked,
            "transitions": [t.to_dict() for t in self.transitions],
        }


def expand_wall_clock_recurrence(
    pattern: pd.Series,
    until: date,
    tz: str,
    resolution: timedelta,
    same_weekday_only: bool = False,
    policy: DstPolicy = DstPolicy(),
    on_days: Callable[[date], bool] | None = None,
    include_pattern: bool = False,
) -> tuple[pd.Series, RecurrenceReport]:
    """Repeat a pattern of sensor values daily (or weekly) by local wall-clock time, until a given date.

    Each source slot is mapped by its local time-of-day, so a value at 07:00 lands at 07:00 on every repeat, also across a DST transition.
    The first repeat directly follows the pattern (one day or one week later).
    Repeating stops at the end of `until`: a slot is written only if it starts before the local midnight that follows it,
    so the last repeat is cut short there if it would run into the next day.

    For a sensor with a resolution, the result lists every slot from the first written to the last, at that resolution,
    so the gaps between repeats show as NaN, just like a NaN in the pattern or an omitted slot.
    Where the resolution is coarser than a clock change (such as hourly data on Lord Howe Island, whose clocks shift by 30 minutes),
    the slots stay on their local time, so the result is not regular in absolute time around that change,
    and it holds extra events: a slot only partly skipped starts when the clock resumes,
    and the repeated part of the clock that no slot starts in is filled by one more event of the preceding slot, ending where the next slot starts.
    Such events may overlap their neighbours.
    For an instantaneous sensor (a zero resolution), the result holds only the repeated instants.

    :param pattern:             Values with a timezone-aware index, regular at the sensor resolution; NaN means "no value".
    :param until:               The last local date (in `tz`) to write values on, inclusive.
    :param tz:                  The sensor's timezone, as an IANA name, such as "Europe/Amsterdam".
    :param resolution:          The sensor's event resolution, or zero for an instantaneous sensor.
    :param same_weekday_only:   Repeat every 7 days instead of every day.
    :param policy:              How to resolve DST transitions.
    :param on_days:             Only repeat on the local dates for which this returns True, such as workdays,
                                where a repeat's date is the date its first slot falls on.
    :param include_pattern:     Also return the pattern itself, unless `on_days` leaves out the date it starts on.
    :returns:                   The values, indexed in `tz`, and a report of what DST transitions did to them.
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
    # Which occurrences to write, by the local date each starts on, where occurrence 0 is the pattern itself.
    first_day = wall_clock[0].date()
    kept_occurrences = np.array(
        [
            (k > 0 or include_pattern)
            and (on_days is None or on_days(first_day + k * period))
            for k in range(0, n_occurrences + 1)
        ],
        dtype=bool,
    )
    n_kept_repeats = int(kept_occurrences[1:].sum())
    pattern_included = bool(kept_occurrences[0])
    if not kept_occurrences.any():
        empty = pd.Series(
            [], index=pd.DatetimeIndex([], tz=tz), dtype=float, name=pattern.name
        )
        return empty, RecurrenceReport(period=period_name, n_occurrences=0)

    end_instant = end_of_until.tz_localize(
        tz, ambiguous=True, nonexistent="shift_forward"
    )
    written_from = local_index[0] if pattern_included else local_index[-1] + resolution
    transitions = [
        t
        for t in _clock_changes(tz, local_index[0], end_instant)
        if t[0] >= written_from
    ]

    expanded, effects = _expand_wall_clock(
        pattern,
        wall_clock,
        kept_occurrences,
        period,
        resolution,
        end_of_until,
        tz,
        policy,
        transitions,
    )
    described = [_describe(t, **effects) for t in transitions]
    report = RecurrenceReport(
        period=period_name,
        n_occurrences=n_kept_repeats,
        pattern_included=pattern_included,
        n_transitions_checked=len(described),
        transitions=tuple(t for t in described if t.has_effect),
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
    transitions: list[tuple[pd.Timestamp, timedelta, timedelta]],
) -> tuple[pd.Series, dict]:
    """Repeat the pattern on the wall clock, and localize each repeat in the sensor's timezone.

    Occurrence 0 is the pattern itself.
    Returns the expanded series, and the naive local start times of the slots with a value that were omitted, duplicated or shifted,
    where extra fill events are listed per transition, as their slot lies outside the repeated part of the clock.
    """
    if policy.nonexistent is not NonexistentTime.DROP:
        raise NotImplementedError(f"DST policy {policy.nonexistent} is not supported.")
    if policy.ambiguous is not AmbiguousTime.BOTH:
        raise NotImplementedError(f"DST policy {policy.ambiguous} is not supported.")

    # Repeats are stepped on naive local times, where adding whole days always keeps the time-of-day.
    # Don't step tz-aware times instead: freq="24h", pd.Timedelta("1D") and pd.offsets.Day(1) are absolute (Day is a Tick offset, despite its name, at least before pandas 3),
    # and even a calendar-aware pd.DateOffset(days=1) can only land on one of the two instants of an ambiguous local time, where we may want both.
    n_occurrences = len(kept_occurrences)
    steps = pd.TimedeltaIndex(np.arange(0, n_occurrences) * pd.Timedelta(period))
    targets = pd.DatetimeIndex(
        (wall_clock.values[None, :] + steps.values[:, None]).ravel()
    )
    values = np.tile(pattern.to_numpy(dtype=float), n_occurrences)
    keep = (targets < end_of_until) & np.repeat(kept_occurrences, len(pattern))
    repeated = pd.Series(values[keep], index=targets[keep])

    if resolution > timedelta(0):
        # Lay the values on a contiguous wall-clock grid, so the gaps between repeats show as NaN.
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

    # A slot whose start is skipped, but whose end is not, starts when the clock resumes, which is the instant of the clock change.
    # Don't use nonexistent="shift_forward" for this: pandas shifts by a whole hour, which overshoots a 30-minute change.
    shifted: np.ndarray = np.zeros(len(repeated), dtype=bool)
    resumed: list[pd.Timestamp] = []
    if resolution > timedelta(0):
        for instant, before, after in transitions:
            if after <= before:
                continue
            window_start = instant.tz_convert("UTC").tz_localize(None) + before
            window_end = window_start + (after - before)
            partly_skipped = (
                (repeated.index >= window_start)
                & (repeated.index < window_end)
                & (repeated.index + resolution > window_end)
            )
            shifted |= partly_skipped
            resumed += [instant.tz_convert(tz)] * int(partly_skipped.sum())
    omitted = nonexistent & ~shifted

    starts = (
        first[~nonexistent]
        .append(second[ambiguous])
        .append(pd.DatetimeIndex(resumed, tz=tz))
    )
    expanded_values = np.concatenate(
        [
            repeated.to_numpy()[~nonexistent],
            repeated.to_numpy()[ambiguous],
            repeated.to_numpy()[shifted],
        ]
    )

    # Fill the repeated part of the clock that no slot starts in, from the slot that precedes it.
    filled: dict[pd.Timestamp, list[pd.Timestamp]] = {}
    if timedelta(0) < resolution < timedelta(days=1):
        fill_starts, fill_values = [], []
        for instant, before, after in transitions:
            if after >= before:
                continue
            window_start = instant.tz_convert("UTC").tz_localize(None) + after
            window_end = window_start + (before - after)
            in_window = repeated.index[
                (repeated.index >= window_start) & (repeated.index < window_end)
            ]
            next_start = in_window[0] if len(in_window) else window_end
            preceding = repeated.index[repeated.index <= window_start]
            if next_start == window_start or len(preceding) == 0:
                continue
            slot = preceding[-1]
            if np.isnan(repeated[slot]):
                continue
            # The extra event ends where the next slot starts on the second run of the clock.
            fill_starts.append(
                (instant + (next_start - window_start) - resolution).tz_convert(tz)
            )
            fill_values.append(repeated[slot])
            filled[instant] = [slot]
        if fill_starts:
            starts = starts.append(pd.DatetimeIndex(fill_starts))
            expanded_values = np.concatenate([expanded_values, fill_values])

    expanded = pd.Series(expanded_values, index=starts, name=pattern.name).sort_index()

    effects = dict(
        omitted=list(repeated.index[omitted & has_value]),
        duplicated=list(repeated.index[ambiguous & has_value]),
        shifted=list(repeated.index[shifted & has_value]),
        filled=filled,
    )
    return expanded, effects


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
    shifted: list[pd.Timestamp],
    filled: dict[pd.Timestamp, list[pd.Timestamp]],
) -> DstTransition:
    """Describe one clock change, with the omitted, duplicated and shifted slots that fall within it."""
    instant, before, after = change
    naive_instant = instant.tz_convert("UTC").tz_localize(None)
    # The wall-clock window that is skipped (spring forward) or that occurs twice (fall back).
    window_start = naive_instant + min(before, after)
    window_end = naive_instant + max(before, after)

    def in_window(slots: list[pd.Timestamp]) -> tuple[time, ...]:
        return tuple(t.time() for t in slots if window_start <= t < window_end)

    spring_forward = after > before
    return DstTransition(
        date=(naive_instant + before).date(),
        kind="spring-forward" if spring_forward else "fall-back",
        shift=abs(after - before),
        wall_clock_start=window_start.time(),
        wall_clock_end=window_end.time(),
        omitted=in_window(omitted) if spring_forward else (),
        duplicated=(
            ()
            if spring_forward
            else tuple(t.time() for t in filled.get(instant, []))
            + in_window(duplicated)
        ),
        shifted=in_window(shifted) if spring_forward else (),
    )
