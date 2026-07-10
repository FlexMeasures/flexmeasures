"""Duplicate event labels in schedule input reads must not crash the job.

Observed in the FLEXED community co-simulation: reading a battery's soc-minima
sensor raised "cannot reindex on an axis with duplicate labels" inside
StorageScheduler._prepare, failing every re-triggered scheduling job (the RQ
failed-job registry holds the tracebacks). Duplicates arise when beliefs about
the same event survive per-source belief selection, e.g. after a data source
churned versions between posts.
"""

from datetime import timedelta

import pandas as pd
import pytest

from flexmeasures import Sensor
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.models.planning.utils import (
    _resolve_duplicate_events,
    get_continuous_series_sensor_or_quantity,
)


@pytest.mark.parametrize(
    "resolve_overlaps, expected", [("first", 1.0), ("max", 2.0), ("min", 1.0)]
)
def test_resolve_duplicate_events(resolve_overlaps, expected):
    index = pd.DatetimeIndex(
        ["2020-01-01T00:00+01", "2020-01-01T00:00+01", "2020-01-01T01:00+01"],
        name="event_start",
    )
    df = pd.DataFrame({"event_value": [1.0, 2.0, 3.0]}, index=index)
    resolved = _resolve_duplicate_events(df, resolve_overlaps)
    assert not resolved.index.has_duplicates
    assert resolved["event_value"].iloc[0] == expected
    assert resolved["event_value"].iloc[-1] == 3.0
    # A frame without duplicates passes through unchanged
    assert _resolve_duplicate_events(resolved, resolve_overlaps) is resolved


def test_two_sources_same_event_does_not_crash(db, building):
    """Two sources with beliefs about the same event: reads must stay usable."""
    sensor = Sensor(
        name="dup belief sensor",
        generic_asset=building,
        unit="MW",
        event_resolution=timedelta(0),
    )
    sources = [
        DataSource(name=f"dup source {n}", type="demo script") for n in ("a", "b")
    ]
    db.session.add_all([sensor, *sources])
    db.session.flush()
    start = pd.Timestamp("2020-01-01T00:00:00", tz="Europe/Amsterdam")
    for value, source in zip((1.0, 2.0), sources):
        db.session.add(
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=start,
                belief_time=start - timedelta(hours=1),
                event_value=value,
            )
        )
    db.session.commit()

    series = get_continuous_series_sensor_or_quantity(
        variable_quantity=sensor,
        unit="MW",
        query_window=(start, start + timedelta(hours=1)),
        resolution=timedelta(minutes=15),
        resolve_overlaps="min",
    )
    assert series.notna().any()
    assert set(series.dropna().unique()) <= {1.0, 2.0}
