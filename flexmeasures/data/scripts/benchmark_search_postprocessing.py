"""Benchmark search_beliefs post-processing on synthetic data (no database needed).

Usage:

    python flexmeasures/data/scripts/benchmark_search_postprocessing.py

Run it twice to compare implementations, e.g. once on main and once on a perf branch.
On code that predates the vectorized implementations, the script falls back to
timing verbatim copies of the previous per-row implementations, so the printed
table is comparable across branches.
"""

from __future__ import annotations

import time
from datetime import timedelta
from statistics import median

import numpy as np
import pandas as pd
import timely_beliefs as tb
from packaging.version import Version

from flexmeasures.data.models.data_sources import DataSource, keep_latest_version

SIZES = [10_000, 100_000]
REPS = 3


def make_bdf(
    n_rows: int, sources: list[DataSource], cps: tuple = (0.5,)
) -> tb.BeliefsDataFrame:
    sensor = tb.Sensor("bench sensor", event_resolution=timedelta(minutes=15))
    n_belief_times = 2
    n_events = max(1, n_rows // (n_belief_times * len(cps)))
    event_starts = pd.date_range("2025-01-01", periods=n_events, freq="15min", tz="UTC")
    belief_times = pd.date_range(
        "2024-12-01", periods=n_belief_times, freq="1h", tz="UTC"
    )
    rng = np.random.default_rng(0)
    records = [
        (event_start, belief_time, sources[int(rng.integers(len(sources)))], cp, value)
        for event_start in event_starts
        for belief_time in belief_times
        for cp, value in [(cp, float(rng.random())) for cp in cps]
    ]
    df = pd.DataFrame(
        records,
        columns=[
            "event_start",
            "belief_time",
            "source",
            "cumulative_probability",
            "event_value",
        ],
    )
    return tb.BeliefsDataFrame(df, sensor=sensor)


def timeit(label: str, fn) -> None:
    times = []
    for _ in range(REPS):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    print("{:<60} {:>10.1f} ms".format(label, median(times) * 1000))


def deterministic_selection(bdf: tb.BeliefsDataFrame) -> tb.BeliefsDataFrame:
    """One deterministic belief per event (deterministic multi-source data)."""
    try:
        from flexmeasures.data.models.time_series import (
            _select_latest_version_and_belief_per_event,
        )

        return _select_latest_version_and_belief_per_event(bdf)
    except ImportError:
        # Fallback: previous implementation (from TimedBelief.search)
        bdf = bdf.sort_values(
            by=["event_start", "source", "belief_time"],
            ascending=[True, False, False],
            key=lambda col: (
                col.map(lambda s: Version(s.version if s.version else "0.0.0"))
                if col.name == "source"
                else col
            ),
        )
        return bdf.groupby(level=["event_start"], group_keys=False).apply(
            lambda x: x.head(1)
        )


def compress_records(df: pd.DataFrame, sensor_id: int):  # noqa: C901
    try:
        from flexmeasures.data.models.time_series import compress_belief_records

        return compress_belief_records(df, sensor_id)
    except ImportError:
        # Fallback: previous implementation (from Sensor.search_beliefs)
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
                elif hasattr(value, "item"):
                    record[key] = value.item()
            all_records.append(record)
        return all_records, sources_metadata


def main():
    single_source = [
        DataSource(id=1, name="s1", model="model 1", type="forecaster", version="1.0")
    ]
    distinct_sources = [
        DataSource(id=1, name="s1", model="model 1", type="forecaster", version="1.0"),
        DataSource(id=2, name="s2", model="model 2", type="scheduler"),
        DataSource(id=3, name="s3", model="model 3", type="reporter", version="2.0"),
    ]
    versioned_sources = [
        DataSource(
            id=1, name="s1", model="model 1", type="forecaster", version="0.1.0"
        ),
        DataSource(
            id=2, name="s1", model="model 1", type="forecaster", version="0.2.0"
        ),
        DataSource(id=3, name="s2", model="model 2", type="scheduler"),
    ]

    for n_rows in SIZES:
        print("--- {} rows ---".format(n_rows))
        for mix_label, sources in [
            ("1 source", single_source),
            ("3 sources, distinct groups", distinct_sources),
            ("3 sources, 2 versions of one", versioned_sources),
        ]:
            bdf = make_bdf(n_rows, sources)
            timeit(
                "keep_latest_version           ({})".format(mix_label),
                lambda bdf=bdf: keep_latest_version(bdf),
            )
        bdf = make_bdf(n_rows, versioned_sources)
        timeit(
            "deterministic belief per event (3 sources, 2 versions)",
            lambda bdf=bdf: deterministic_selection(bdf),
        )
        bdf_prob = make_bdf(n_rows, versioned_sources, cps=(0.1587, 0.5, 0.8413))
        timeit(
            "keep_latest_version           (probabilistic, 3 sources)",
            lambda bdf=bdf_prob: keep_latest_version(bdf),
        )
        df = make_bdf(n_rows, distinct_sources).reset_index()
        timeit(
            "compress_belief_records       (3 sources, distinct groups)",
            lambda df=df: compress_records(df, sensor_id=42),
        )


if __name__ == "__main__":
    main()
