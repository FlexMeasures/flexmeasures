"""Taking the beliefs of an instantaneous sensor onto the slots a forecast steps through.

An instantaneous sensor records a state at instants, such as a temperature or a setpoint.
Under the default ``ffill`` interpolation, a recorded state holds until the next one (step-before),
for at most the sensor's ``interpolation_limit``.
How long a value holds runs along event time, but who could know it, and when, differs:

- A measurement (a belief that is realized, as the sensor's knowledge horizon defines it) holds until the next measurement.
  A held value is only known once its instant has come, so its belief time is the later of its recording and that instant.
- A forecast holds until the next event in the same forecast, i.e. by the same source at the same belief time.
  A held value is part of that forecast, so it keeps the forecast's belief time, and stays a forecast.
"""

from __future__ import annotations

from datetime import timedelta

import isodate
import numpy as np
import pandas as pd

from flexmeasures.data.models.time_series import Sensor

INTERPOLATION_POLICIES = ("ffill", "none")
DEFAULT_INTERPOLATION_POLICY = "ffill"


class InterpolationAttributeError(ValueError):
    """Raised when a sensor's ``interpolation`` or ``interpolation_limit`` attribute cannot be used."""


# Marks an interpolation limit to be inferred from the data, as opposed to no limit at all (None).
INFER_LIMIT = "infer"


def _empty() -> pd.DataFrame:
    """A frame without beliefs, typed like the frames this module returns, so that it merges with the frames of other sensors."""
    return pd.DataFrame(
        {
            "event_start": pd.Series(dtype="datetime64[ns, UTC]"),
            "belief_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "source": pd.Series(dtype=object),
            "event_value": pd.Series(dtype=float),
            "is_realized": pd.Series(dtype=bool),
        }
    )


def interpolation_policy(sensor: Sensor) -> tuple[str, timedelta | None | str]:
    """Read and check how to interpolate between the readings of an instantaneous sensor.

    :param sensor:  The instantaneous sensor.
    :returns:       The policy ("ffill" or "none"), and the interpolation limit:
                    a duration, None for no limit, or ``INFER_LIMIT`` when the attribute is not set.
    :raises InterpolationAttributeError: If either attribute holds a value that cannot be used.
    """
    policy = sensor.get_attribute("interpolation", DEFAULT_INTERPOLATION_POLICY)
    if policy not in INTERPOLATION_POLICIES:
        raise InterpolationAttributeError(
            f"Sensor {sensor.id} has an 'interpolation' attribute of {policy!r}; use one of {', '.join(repr(p) for p in INTERPOLATION_POLICIES)}."
        )
    if "interpolation_limit" not in (sensor.attributes or {}):
        return policy, INFER_LIMIT
    limit = sensor.attributes["interpolation_limit"]
    if limit is None:
        return policy, None
    try:
        duration = isodate.parse_duration(limit) if isinstance(limit, str) else None
    except isodate.ISO8601Error:
        duration = None
    if not isinstance(duration, timedelta) or duration <= timedelta(0):
        raise InterpolationAttributeError(
            f"Sensor {sensor.id} has an 'interpolation_limit' attribute of {limit!r}; use a positive ISO 8601 duration of fixed length, such as 'PT2H', or null for no limit."
        )
    return policy, duration


def infer_interpolation_limit(event_starts: pd.Index) -> timedelta | None:
    """Return twice the most common duration between the given event starts, or None (no limit) if there are fewer than two.

    :param event_starts:    Event starts of the sensor's measurements.
    """
    event_starts = pd.DatetimeIndex(pd.unique(event_starts)).sort_values()
    if len(event_starts) < 2:
        return None
    gaps = pd.Series(event_starts[1:] - event_starts[:-1])
    return (2 * gaps.mode().iloc[0]).to_pytimedelta()


def _grid_index(
    times: pd.Series, anchor: pd.Timestamp, resolution: timedelta, ceil: bool
) -> np.ndarray:
    """Number of grid steps from the anchor to each time, rounded up (ceil) or down."""
    steps = (times - anchor) / resolution
    return np.ceil(steps).astype("int64") if ceil else np.floor(steps).astype("int64")


def _segments(
    beliefs: pd.DataFrame,
    group_columns: list[str],
    limit: timedelta | None,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Add the end of the time each belief holds for: the next event in its group, capped by the limit and the end.

    :param beliefs:         Frame with "event_start", sorted within groups by "event_start".
    :param group_columns:   Columns whose values make up one sequence of events (none: all beliefs are one sequence).
    """
    if group_columns:
        grouped = beliefs.groupby(group_columns, sort=False)["event_start"]
        distinct_next = grouped.transform(lambda s: _next_distinct(s))
    else:
        distinct_next = _next_distinct(beliefs["event_start"])
    hold_until = distinct_next.fillna(end)
    if limit is not None:
        hold_until = np.minimum(hold_until, beliefs["event_start"] + limit)
    return beliefs.assign(hold_until=np.minimum(hold_until, end))


def _next_distinct(event_starts: pd.Series) -> pd.Series:
    """For each event start (in UTC), the next later event start in the series (NaT for the last)."""
    as_ns = pd.DatetimeIndex(event_starts).tz_convert("UTC").asi8
    distinct = np.unique(as_ns)
    positions = np.searchsorted(distinct, as_ns, side="right")
    has_next = positions < len(distinct)
    nxt = np.full(len(as_ns), np.iinfo("int64").min, dtype="int64")
    nxt[has_next] = distinct[positions[has_next]]
    return pd.Series(
        pd.to_datetime(np.where(has_next, nxt, np.iinfo("int64").min), utc=True),
        index=event_starts.index,
    ).where(has_next)


def sample_instantaneous_beliefs(
    beliefs: pd.DataFrame,
    sensor: Sensor,
    resolution: timedelta,
    anchor: pd.Timestamp,
    end: pd.Timestamp,
    period: bool,
    policy: str = DEFAULT_INTERPOLATION_POLICY,
    limit: timedelta | None | str = INFER_LIMIT,
) -> pd.DataFrame:
    """Take the beliefs of an instantaneous sensor onto a grid of instants, or of periods, a ``resolution`` apart.

    :param beliefs:     Flat frame with the columns "event_start", "belief_time", "source", "event_value" and "is_realized",
                        the latter telling which beliefs are measurements, as the sensor's knowledge horizon defines it for their own events.
    :param sensor:      The instantaneous sensor, whose knowledge horizon flags the emitted rows.
    :param resolution:  Duration between grid instants.
    :param anchor:      A grid instant, which aligns the grid.
    :param end:         No value is held up to or beyond this time.
    :param period:      If True, each row stands for the period from a grid instant until the next,
                        with the time-weighted mean of the held values over that period (rows for periods not fully covered are left out).
                        Otherwise, each row stands for the value at a grid instant.
    :param policy:      "ffill" to hold values (step-before), or "none" to use only readings exactly on the grid.
    :param limit:       Longest time a value holds for (unlike pandas' ``limit``, a duration rather than a number of rows),
                        None for no limit, or ``INFER_LIMIT`` for twice the most common duration between the measurements.
    :returns:           Flat frame with the columns "event_start", "belief_time", "source", "event_value" and "is_realized".
    """
    columns = ["event_start", "belief_time", "source", "event_value", "is_realized"]
    if beliefs.empty:
        return _empty()
    beliefs = beliefs[columns].copy()
    for column in ("event_start", "belief_time"):
        beliefs[column] = pd.to_datetime(beliefs[column], utc=True)
    anchor = (
        pd.Timestamp(anchor).tz_convert("UTC")
        if pd.Timestamp(anchor).tzinfo
        else pd.Timestamp(anchor).tz_localize("UTC")
    )
    end = (
        pd.Timestamp(end).tz_convert("UTC")
        if pd.Timestamp(end).tzinfo
        else pd.Timestamp(end).tz_localize("UTC")
    )
    beliefs["is_realized"] = beliefs["is_realized"].astype(bool)
    measurements = beliefs[beliefs["is_realized"]]
    forecasts = beliefs[~beliefs["is_realized"]]
    if limit == INFER_LIMIT:
        limit = infer_interpolation_limit(measurements["event_start"])

    if policy == "none":
        # Only readings exactly on the grid count, and each stands for its own instant (or the period it starts).
        on_grid = beliefs[
            ((beliefs["event_start"] - anchor) % resolution) == timedelta(0)
        ]
        rows = on_grid.assign(t=on_grid["event_start"])
        held_measurement = rows["is_realized"]
        known_from = rows["t"] + resolution if period else rows["t"]
        rows["emitted_belief_time"] = np.where(
            held_measurement,
            np.maximum(rows["belief_time"], known_from),
            rows["belief_time"],
        )
        rows["emitted_belief_time"] = pd.to_datetime(
            rows["emitted_belief_time"], utc=True
        )
        return _finish(rows, sensor, resolution if period else timedelta(0))

    measurements = measurements.sort_values(
        ["event_start", "belief_time"], kind="stable"
    )
    measurements = _segments(measurements, [], limit, end)
    forecasts = forecasts.assign(
        source_id_=forecasts["source"].map(lambda s: getattr(s, "id", s))
    )
    forecasts = forecasts.sort_values(
        ["source_id_", "belief_time", "event_start"], kind="stable"
    )
    forecasts = _segments(forecasts, ["source_id_", "belief_time"], limit, end)

    if period:
        rows = _concat(
            _period_means(
                _latest_per_event(measurements), resolution, anchor, measurement=True
            ),
            _period_means(forecasts, resolution, anchor, measurement=False),
        )
        return _finish(rows, sensor, resolution)

    rows = _concat(
        _instants(measurements, resolution, anchor, measurement=True),
        _instants(forecasts, resolution, anchor, measurement=False),
    )
    return _finish(rows, sensor, timedelta(0))


def _concat(*frames: pd.DataFrame) -> pd.DataFrame:
    """Concatenate the frames that have rows."""
    frames_with_rows = [frame for frame in frames if not frame.empty]
    if not frames_with_rows:
        return pd.DataFrame()
    return pd.concat(frames_with_rows, ignore_index=True)


def _latest_per_event(measurements: pd.DataFrame) -> pd.DataFrame:
    """Keep the latest measurement of each event, as a period's mean can only be formed from one value per event."""
    return measurements.sort_values(
        ["event_start", "belief_time"], kind="stable"
    ).drop_duplicates("event_start", keep="last")


def _instants(
    segments: pd.DataFrame,
    resolution: timedelta,
    anchor: pd.Timestamp,
    measurement: bool,
) -> pd.DataFrame:
    """One row per grid instant that each belief holds for."""
    if segments.empty:
        return segments.assign(
            t=pd.Series(dtype="datetime64[ns, UTC]"),
            emitted_belief_time=pd.Series(dtype="datetime64[ns, UTC]"),
        )
    first = _grid_index(segments["event_start"], anchor, resolution, ceil=True)
    # The hold ends before hold_until, so the last instant is the one before it.
    stop = _grid_index(segments["hold_until"], anchor, resolution, ceil=True)
    counts = np.maximum(stop - first, 0)
    repeated = segments.loc[segments.index.repeat(counts)].copy()
    offsets = (
        np.concatenate([np.arange(n) for n in counts])
        if counts.sum()
        else np.array([], dtype="int64")
    )
    steps = np.repeat(first, counts) + offsets
    repeated["t"] = anchor + pd.to_timedelta(
        steps * (resolution / timedelta(microseconds=1)), unit="us"
    )
    if measurement:
        repeated["emitted_belief_time"] = np.maximum(
            repeated["belief_time"], repeated["t"]
        )
    else:
        repeated["emitted_belief_time"] = repeated["belief_time"]
    repeated["emitted_belief_time"] = pd.to_datetime(
        repeated["emitted_belief_time"], utc=True
    )
    return repeated


def _period_means(
    segments: pd.DataFrame,
    resolution: timedelta,
    anchor: pd.Timestamp,
    measurement: bool,
) -> pd.DataFrame:
    """One row per grid period that the held values cover entirely, with their time-weighted mean.

    Measurements form one step function; forecasts form one per forecast (same source and belief time).
    A measurement row is known once the period has ended and all its contributing measurements were recorded;
    a forecast row is known when its forecast was made.
    """
    out_columns = [
        "t",
        "emitted_belief_time",
        "source",
        "event_value",
        "is_realized",
        "belief_time",
    ]
    if segments.empty:
        return pd.DataFrame(columns=out_columns)
    group_keys = ["source_id_", "belief_time"] if not measurement else None
    records = []
    groups = (
        segments.groupby(group_keys, sort=False) if group_keys else [(None, segments)]
    )
    for _, group in groups:
        totals: dict[int, list] = {}
        for start, stop, value, belief_time, source in zip(
            group["event_start"],
            group["hold_until"],
            group["event_value"],
            group["belief_time"],
            group["source"],
        ):
            if stop <= start:
                continue
            k = int(np.floor((start - anchor) / resolution))
            while True:
                slot_start = anchor + k * resolution
                slot_end = slot_start + resolution
                overlap = min(stop, slot_end) - max(start, slot_start)
                if overlap > timedelta(0):
                    total = totals.setdefault(
                        k, [timedelta(0), 0.0, belief_time, source]
                    )
                    total[0] += overlap
                    total[1] += value * (overlap / resolution)
                    total[2] = max(total[2], belief_time)
                if slot_end >= stop:
                    break
                k += 1
        for k, (covered, weighted, latest_belief_time, source) in totals.items():
            if covered < resolution:
                continue  # a period only partly covered is missing
            t = anchor + k * resolution
            emitted = (
                max(latest_belief_time, t + resolution)
                if measurement
                else latest_belief_time
            )
            records.append(
                (t, emitted, source, weighted, measurement, latest_belief_time)
            )
    return pd.DataFrame.from_records(records, columns=out_columns)


def _finish(
    rows: pd.DataFrame, sensor: Sensor, event_resolution: timedelta
) -> pd.DataFrame:
    """Keep one row per instant (or period), belief time and source, and flag the rows that are realized for the emitted events."""
    if rows.empty:
        return _empty()
    rows = rows.assign(source_id_=rows["source"].map(lambda s: getattr(s, "id", s)))
    # Of several beliefs that end up at one instant and belief time (such as a measurement and its correction, both recorded before that instant),
    # the one recorded last is the one known then.
    rows = rows.sort_values(
        ["t", "emitted_belief_time", "source_id_", "belief_time"], kind="stable"
    ).drop_duplicates(["t", "emitted_belief_time", "source_id_"], keep="last")
    knowledge_times = pd.DatetimeIndex(
        sensor.knowledge_time(pd.DatetimeIndex(rows["t"]), event_resolution)
    ).tz_convert("UTC")
    out = pd.DataFrame(
        {
            "event_start": pd.DatetimeIndex(rows["t"]),
            "belief_time": pd.DatetimeIndex(rows["emitted_belief_time"]),
            "source": rows["source"].to_numpy(),
            "event_value": rows["event_value"].astype(float).to_numpy(),
        }
    )
    out["is_realized"] = np.asarray(out["belief_time"] >= knowledge_times)
    return out.reset_index(drop=True)
