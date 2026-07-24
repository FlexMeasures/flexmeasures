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


def naive_compress_belief_records(df: pd.DataFrame, sensor_id: int):
    """Reference implementation: the previous per-row loop."""
    sources_metadata: dict = {}
    all_records = []
    for _, row in df.iterrows():
        source_obj = row.get("source")
        if (
            source_obj
            and hasattr(source_obj, "id")
            and source_obj.id not in sources_metadata
        ):
            source_dict = source_obj.as_dict
            sources_metadata[source_obj.id] = {
                "name": source_dict.get("name", ""),
                "model": source_dict.get("model", ""),
                "version": source_dict.get("version", ""),
                "type": source_dict.get("type", "other"),
                "raw_type": source_dict.get("raw_type", ""),
                "display_type": source_dict.get(
                    "display_type", source_dict.get("type", "other")
                ),
                "description": source_dict.get("description", ""),
            }
        record = {
            "ts": int(row["event_start"].timestamp() * 1000),
            "sid": sensor_id,
            "val": row["event_value"],
        }
        if source_obj and hasattr(source_obj, "id"):
            record["src"] = source_obj.id
        if "belief_time" in row and pd.notnull(row["belief_time"]):
            record["bt"] = int(row["belief_time"].timestamp() * 1000)
        if "belief_horizon" in row and pd.notnull(row["belief_horizon"]):
            record["bh"] = int(row["belief_horizon"].total_seconds())
        if "cumulative_probability" in row and pd.notnull(
            row["cumulative_probability"]
        ):
            record["cp"] = row["cumulative_probability"]
        for key, value in record.items():
            if pd.isna(value):
                record[key] = None
            elif isinstance(value, pd.Timestamp):
                record[key] = int(value.timestamp() * 1000)
            elif isinstance(value, (pd.Timedelta, timedelta)):
                record[key] = int(value.total_seconds())
            elif hasattr(value, "item"):  # numpy types
                record[key] = value.item()
        all_records.append(record)
    return all_records, sources_metadata


def test_compress_belief_records_equivalence():
    import json

    from flexmeasures.data.models.time_series import compress_belief_records

    rng = np.random.default_rng(11)
    sources = [
        DataSource(id=1, name="s1", model="model 1", type="forecaster", version="2.0"),
        DataSource(id=2, name="s2", model="model 2", type="scheduler"),
    ]
    sensor = tb.Sensor("compress sensor", event_resolution=timedelta(hours=1))
    event_starts = pd.date_range("2025-01-01", periods=6, freq="1h", tz="UTC")
    # Belief times both before and after the events (i.e. positive and negative
    # belief horizons), with sub-second components (like real recording times)
    belief_times = pd.date_range("2024-12-31", periods=60, freq="1h", tz="UTC")
    beliefs = []
    for i in range(30):
        cps = [(0.5, float(rng.random()))]
        if rng.random() > 0.7:
            cps = [(0.3, float(rng.random())), (0.7, float(rng.random()))]
        belief_time = belief_times[rng.integers(len(belief_times))] + pd.Timedelta(
            microseconds=int(rng.integers(0, 1_000_000))
        )
        for cp, value in cps:
            beliefs.append(
                tb.TimedBelief(
                    sensor=sensor,
                    source=sources[rng.integers(len(sources))],
                    event_start=event_starts[rng.integers(len(event_starts))],
                    belief_time=belief_time,
                    cumulative_probability=cp,
                    event_value=np.nan if rng.random() > 0.8 else value,
                )
            )
    bdf = tb.BeliefsDataFrame(beliefs)

    # belief_time-indexed frame
    df = bdf.reset_index()
    result = compress_belief_records(df, sensor_id=42)
    expected = naive_compress_belief_records(df, sensor_id=42)
    assert json.dumps(result[0]) == json.dumps(expected[0])
    assert json.dumps(result[1]) == json.dumps(expected[1])

    # belief_horizon-indexed frame (and a NaT belief time column for good measure)
    df_horizon = bdf.convert_index_from_belief_time_to_horizon().reset_index()
    result = compress_belief_records(df_horizon, sensor_id=42)
    expected = naive_compress_belief_records(df_horizon, sensor_id=42)
    assert json.dumps(result[0]) == json.dumps(expected[0])
    assert json.dumps(result[1]) == json.dumps(expected[1])
