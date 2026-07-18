"""DB-free equivalence tests for vectorized search_beliefs post-processing."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import timely_beliefs as tb
from packaging.version import Version

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import (
    _select_latest_version_and_belief_per_event,
)


def make_random_deterministic_bdf(
    rng: np.random.Generator, sources: list[DataSource], n_beliefs: int
) -> tb.BeliefsDataFrame:
    sensor = tb.Sensor("postprocessing sensor", event_resolution=timedelta(hours=1))
    event_starts = pd.date_range("2025-01-01", periods=5, freq="1h", tz="UTC")
    belief_times = pd.date_range("2024-12-31", periods=3, freq="1h", tz="UTC")
    beliefs = [
        tb.TimedBelief(
            sensor=sensor,
            source=sources[rng.integers(len(sources))],
            event_start=event_starts[rng.integers(len(event_starts))],
            belief_time=belief_times[rng.integers(len(belief_times))],
            event_value=float(rng.random()),
        )
        for _ in range(n_beliefs)
    ]
    return tb.BeliefsDataFrame(beliefs)


def naive_select_latest_version_and_belief_per_event(
    bdf: tb.BeliefsDataFrame,
) -> tb.BeliefsDataFrame:
    """Reference implementation: per event, pick the belief with the latest
    source version, breaking version ties by most recent belief time."""
    winners: dict = {}
    for i, (event_start, belief_time, source, _cp) in enumerate(bdf.index):
        candidate = (Version(source.version or "0.0.0"), belief_time)
        incumbent = winners.get(event_start)
        if incumbent is None or candidate > incumbent[0]:
            winners[event_start] = (candidate, i)
    winning_rows = {i for _, i in winners.values()}
    return bdf[[i in winning_rows for i in range(len(bdf))]]


def test_select_latest_version_and_belief_per_event_equivalence():
    rng = np.random.default_rng(7)
    sources = [
        DataSource(
            id=i + 1,
            name="s1",
            model="model 1",
            type="forecaster",
            version=version,
        )
        for i, version in enumerate([None, "0.1.0", "0.2.0", "0.2.0", "1.0.0"])
    ]
    for trial in range(10):
        bdf = make_random_deterministic_bdf(
            rng, sources, n_beliefs=int(rng.integers(2, 30))
        )
        result = _select_latest_version_and_belief_per_event(bdf)
        expected = naive_select_latest_version_and_belief_per_event(bdf)
        pd.testing.assert_frame_equal(pd.DataFrame(result), pd.DataFrame(expected))
        # Exactly one belief per event
        assert not result.index.get_level_values("event_start").duplicated().any()
