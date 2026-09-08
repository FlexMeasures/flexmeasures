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
    preferred_sources: list[DataSource] | None = None,
) -> tb.BeliefsDataFrame:
    """Reference implementation, written per row rather than vectorised.

    Per event, keep one belief per family of sources sharing a name, type and model,
    choosing the latest version, then the most recent belief, then the highest source id.
    Then, among those, choose the source the caller named first,
    again falling back on the most recent belief and then the highest source id.
    """
    positions: dict = {}
    for position, source in enumerate(preferred_sources or []):
        positions.setdefault(source.id, position)
    unlisted = len(positions)

    per_family: dict = {}
    for i, (event_start, belief_time, source, _cp) in enumerate(bdf.index):
        family = (event_start, source.name, source.type, source.model)
        candidate = (Version(source.version or "0.0.0"), belief_time, source.id or -1)
        incumbent = per_family.get(family)
        if incumbent is None or candidate > incumbent[0]:
            per_family[family] = (candidate, i)

    winners: dict = {}
    for (event_start, _name, _type, _model), (_key, i) in per_family.items():
        _, belief_time, source, _cp = bdf.index[i]
        # A lower position is preferred, so it is negated to keep "greater is better".
        candidate = (
            -positions.get(source.id, unlisted),
            belief_time,
            source.id or -1,
        )
        incumbent = winners.get(event_start)
        if incumbent is None or candidate > incumbent[0]:
            winners[event_start] = (candidate, i)
    winning_rows = {i for _, i in winners.values()}
    return bdf[[i in winning_rows for i in range(len(bdf))]]


def test_select_latest_version_and_belief_per_event_equivalence():
    """The vectorised choice agrees with the plainly written one, over random frames.

    The sources span two families, so that the two steps of the choice are both exercised,
    and each trial is run with and without a caller's preference.
    """
    rng = np.random.default_rng(7)
    sources = [
        DataSource(id=1, name="s1", model="model 1", type="forecaster", version=None),
        DataSource(
            id=2, name="s1", model="model 1", type="forecaster", version="0.1.0"
        ),
        DataSource(
            id=3, name="s1", model="model 1", type="forecaster", version="0.2.0"
        ),
        DataSource(
            id=4, name="s1", model="model 1", type="forecaster", version="0.2.0"
        ),
        DataSource(id=5, name="s2", model="model 2", type="scheduler", version="1.0.0"),
        DataSource(id=6, name="s2", model="model 2", type="scheduler", version="9.0.0"),
    ]
    for preference in (None, [sources[4], sources[0]], [sources[0], sources[5]]):
        for _ in range(10):
            bdf = make_random_deterministic_bdf(
                rng, sources, n_beliefs=int(rng.integers(2, 30))
            )
            result = _select_latest_version_and_belief_per_event(
                bdf, preferred_sources=preference
            )
            expected = naive_select_latest_version_and_belief_per_event(
                bdf, preferred_sources=preference
            )
            pd.testing.assert_frame_equal(pd.DataFrame(result), pd.DataFrame(expected))
            # Exactly one belief per event
            assert not result.index.get_level_values("event_start").duplicated().any()


def _one_event_frame(
    beliefs: list[tuple[DataSource, str, float]],
) -> tb.BeliefsDataFrame:
    """A frame of beliefs about one event, each given as its source, belief time and value."""
    sensor = tb.Sensor("precedence sensor", event_resolution=timedelta(hours=1))
    event_start = pd.Timestamp("2025-01-01T00:00:00+00:00")
    return tb.BeliefsDataFrame(
        [
            tb.TimedBelief(
                sensor=sensor,
                source=source,
                event_start=event_start,
                belief_time=pd.Timestamp(belief_time),
                event_value=value,
            )
            for source, belief_time, value in beliefs
        ]
    )


def _chosen_value(beliefs, preferred_sources=None) -> float:
    frame = _select_latest_version_and_belief_per_event(
        _one_event_frame(beliefs), preferred_sources=preferred_sources
    )
    assert len(frame) == 1
    return frame["event_value"].iloc[0]


def test_a_later_version_of_one_source_wins_its_family():
    """Within a family, the version says which code produced the value, so it comes first."""
    old = DataSource(id=1, name="rep", model="Rep", type="reporter", version="1.0.0")
    new = DataSource(id=2, name="rep", model="Rep", type="reporter", version="2.0.0")
    # The older version spoke more recently, and still loses.
    assert (
        _chosen_value(
            [(new, "2024-12-31T00:00+00:00", 2.0), (old, "2024-12-31T06:00+00:00", 1.0)]
        )
        == 2.0
    )


def test_versions_are_not_compared_between_families():
    """A version number orders one source's releases, and says nothing about another source.

    A scheduler at v1 and a forecaster at v9 are unrelated numbering,
    so the choice falls to the more recent belief instead.
    """
    scheduler = DataSource(
        id=1, name="Seita", model="StorageScheduler", type="scheduler", version="1"
    )
    forecaster = DataSource(
        id=2, name="Seita", model="Prophet", type="forecaster", version="9"
    )
    assert (
        _chosen_value(
            [
                (scheduler, "2024-12-31T06:00+00:00", 1.0),
                (forecaster, "2024-12-31T00:00+00:00", 9.0),
            ]
        )
        == 1.0
    )


def test_a_caller_that_names_its_sources_says_which_it_prefers():
    """Between families, the order the caller named its sources in decides, whatever the belief times say."""
    meter = DataSource(id=1, name="meter", model="M", type="other")
    scheduler = DataSource(id=2, name="Seita", model="S", type="scheduler")
    beliefs = [
        (meter, "2024-12-31T06:00+00:00", 1.0),
        (scheduler, "2024-12-31T00:00+00:00", 2.0),
    ]
    assert _chosen_value(beliefs, preferred_sources=[scheduler, meter]) == 2.0
    assert _chosen_value(beliefs, preferred_sources=[meter, scheduler]) == 1.0
    # Naming neither leaves the more recent belief to decide.
    assert _chosen_value(beliefs) == 1.0


def test_sources_named_together_share_one_preference():
    """A name can match several sources, and they arrive in no particular order.

    Reading an order into that would let the database decide precedence,
    so one entry is one preference, and the sources in it are told apart by belief time and id instead.
    """
    # Two sources of one name, which is what `source="rep"` would match.
    older = DataSource(id=1, name="rep", model="A", type="reporter")
    newer = DataSource(id=2, name="rep", model="B", type="reporter")
    other = DataSource(id=3, name="other", model="C", type="reporter")
    beliefs = [
        (older, "2024-12-31T06:00+00:00", 1.0),
        (newer, "2024-12-31T00:00+00:00", 2.0),
        (other, "2024-12-31T12:00+00:00", 3.0),
    ]
    # Named first as one entry, the pair outranks the other source, and the fresher of the pair wins.
    assert _chosen_value(beliefs, preferred_sources=[[older, newer], other]) == 1.0
    # Whichever way round that entry lists them, since one entry is one preference.
    assert _chosen_value(beliefs, preferred_sources=[[newer, older], other]) == 1.0
    # Naming the other source first still puts it ahead of both.
    assert _chosen_value(beliefs, preferred_sources=[other, [older, newer]]) == 3.0


def test_an_entry_that_named_nothing_does_not_demote_the_ones_that_did():
    """A caller can name a source this database does not know, and still be heard about the others.

    An unknown id or name leaves an entry that matched nothing,
    and that entry still holds its place, so the sources named after it must keep outranking the unnamed.
    """
    named = DataSource(id=1, name="scheduler", model="S", type="scheduler")
    unnamed = DataSource(id=2, name="meter", model="M", type="other")
    beliefs = [
        (named, "2024-12-31T00:00+00:00", 1.0),
        # The source nobody named holds the fresher belief, so only the naming can decide this.
        (unnamed, "2024-12-31T06:00+00:00", 2.0),
    ]
    # Two entries matched nothing, and the third named the scheduler.
    assert _chosen_value(beliefs, preferred_sources=[[], [], named]) == 1.0


def test_a_tie_no_one_broke_is_answered_the_same_way_every_time():
    """Two sources that nothing else tells apart are settled by the highest id.

    The id does not move when a source is renamed, where sorting on the name would.
    """
    first = DataSource(id=1, name="zzz", model="M", type="reporter")
    second = DataSource(id=2, name="aaa", model="M", type="reporter")
    beliefs = [
        (first, "2024-12-31T00:00+00:00", 1.0),
        (second, "2024-12-31T00:00+00:00", 2.0),
    ]
    assert _chosen_value(beliefs) == 2.0
    # And the same answer whichever order the rows arrive in.
    assert _chosen_value(list(reversed(beliefs))) == 2.0


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
