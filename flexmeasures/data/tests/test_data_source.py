from __future__ import annotations

import pytest
import time
from datetime import datetime, timedelta, timezone
from pytz import UTC

import numpy as np
import pandas as pd
import timely_beliefs as tb
from sqlalchemy import func, insert, select

from flexmeasures.data.models.data_sources import keep_latest_version, DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.models.time_series import Sensor, TimedBelief


def test_get_reporter_from_source(db, app, test_reporter, add_nearby_weather_sensors):

    reporter = test_reporter.data_generator

    reporter_sensor = add_nearby_weather_sensors.get("farther_temperature")

    assert isinstance(reporter, Reporter)
    assert reporter.__class__.__name__ == "TestReporter"

    res = reporter.compute(
        input=[{"sensor": reporter_sensor}],
        output=[{"sensor": reporter_sensor}],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )[0]["data"]

    assert res.lineage.sources[0] == reporter.data_source

    with pytest.raises((AttributeError, TypeError)):
        # Marshmallow 3.x
        #   AttributeError: 'str' object has no attribute 'isoformat'. Did you mean: 'format'?
        # Marshmallow 4.x
        #   TypeError: descriptor 'isoformat' for 'datetime.datetime' objects doesn't apply to a 'str' object
        reporter.compute(
            input=[{"sensor": reporter_sensor}],
            output=[{"sensor": reporter_sensor}],
            start=datetime(2023, 1, 1, tzinfo=UTC),
            end="not a date",
        )


def test_data_source(db, app, test_reporter):
    # get TestReporter class from the data_generators registry
    TestReporter = app.data_generators["reporter"].get("TestReporter")

    reporter1 = TestReporter(config={"a": "1"})

    db.session.add(reporter1.data_source)

    reporter2 = TestReporter(config={"a": "1"})

    # reporter1 and reporter2 have the same data_source because they share the same config
    assert reporter1.data_source == reporter2.data_source
    assert reporter1.data_source.attributes.get("data_generator").get(
        "config"
    ) == reporter2.data_source.attributes.get("data_generator").get("config")

    reporter3 = TestReporter(config={"a": "2"})

    # reporter3 and reporter2 have different data sources because they have different config values
    assert reporter3.data_source != reporter2.data_source
    assert reporter3.data_source.attributes.get("data_generator").get(
        "config"
    ) != reporter2.data_source.attributes.get("data_generator").get("config")

    # recreate reporter3 from its data source
    reporter4 = reporter3.data_source.data_generator

    # check that reporter3 and reporter4 share the same config values
    assert reporter4._config == reporter3._config


def test_data_generator_save_config(db, app, test_reporter, add_nearby_weather_sensors):
    TestReporter = app.data_generators["reporter"].get("TestReporter")

    reporter_sensor = add_nearby_weather_sensors.get("farther_temperature")

    reporter = TestReporter(config={"a": "1"})

    res = reporter.compute(
        input=[{"sensor": reporter_sensor}],
        output=[{"sensor": reporter_sensor}],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )[0]["data"]

    assert res.lineage.sources[0].attributes.get("data_generator").get("config") == {
        "a": "1"
    }

    reporter = TestReporter(config={"a": "1"}, save_config=False)

    res = reporter.compute(
        input=[{"sensor": reporter_sensor}],
        output=[{"sensor": reporter_sensor}],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )[0]["data"]

    # check that the data_generator is not saving the config in the data_source attributes
    assert res.lineage.sources[0].attributes.get("data_generator") == dict()


def test_data_generator_save_parameters(
    db, app, test_reporter, add_nearby_weather_sensors
):
    TestReporter = app.data_generators["reporter"].get("TestReporter")

    reporter_sensor = add_nearby_weather_sensors.get("farther_temperature")

    reporter = TestReporter(config={"a": "1"}, save_parameters=True)

    parameters = {
        "input": [{"sensor": reporter_sensor.id}],
        "output": [{"sensor": reporter_sensor.id}],
        "start": "2023-01-01T00:00:00+00:00",
        "end": "2023-01-02T00:00:00+00:00",
        "b": "test",
    }

    parameters_without_start_end = {
        "input": [{"sensor": reporter_sensor.id}],
        "output": [{"sensor": reporter_sensor.id}],
        "b": "test",
    }

    res = reporter.compute(parameters=parameters)[0]["data"]

    assert res.lineage.sources[0].attributes.get("data_generator").get("config") == {
        "a": "1"
    }

    assert (
        res.lineage.sources[0].attributes.get("data_generator").get("parameters")
        == parameters_without_start_end
    )

    dg2 = reporter.data_source.data_generator

    parameters_2 = {
        "start": "2023-01-01T10:00:00+00:00",
        "end": "2023-01-02T00:00:00+00:00",
        "b": "test2",
    }

    res = dg2.compute(parameters=parameters_2)[0]["data"]

    # check that compute gets data stored in the DB (i.e. `input`/`output`) and updated data
    # from the method call (e.g. field `b``)
    assert dg2._parameters["b"] == parameters_2["b"]
    assert dg2._parameters["start"].isoformat() == parameters_2["start"]


@pytest.mark.parametrize(
    "source_type, expected_type, expected_display_type",
    [
        ("forecaster", "forecaster", "forecaster"),
        ("forecasting script", "forecaster", "forecaster"),
        ("scheduler", "scheduler", "scheduler"),
        ("scheduling script", "scheduler", "scheduler"),
        ("reporter", "other", "reporter"),
        ("demo script", "other", "demo script"),
        ("", "other", "other"),
    ],
)
def test_data_source_as_dict_keeps_raw_and_display_type(
    source_type: str, expected_type: str, expected_display_type: str
):
    source = DataSource(
        name="FlexMeasures",
        type=source_type,
        model="PandasReporter",
        version="1",
    )

    source_dict = source.as_dict

    assert source_dict["model"] == "PandasReporter"
    assert source_dict["type"] == expected_type
    assert source_dict["raw_type"] == source_type
    assert source_dict["display_type"] == expected_display_type
    assert source_dict["version"] == "1"


def test_keep_last_version():
    s1 = DataSource(
        id=1, name="s1", model="model 1", type="forecaster", version="0.1.0"
    )
    s2 = DataSource(id=2, name="s1", model="model 1", type="forecaster")
    s3 = DataSource(id=3, name="s1", model="model 2", type="forecaster")
    s4 = DataSource(id=4, name="s1", model="model 2", type="scheduler")
    s5 = DataSource(id=5, name="s1", model="model 2", type="scheduler")

    def create_dummy_frame(sources: list[DataSource]) -> tb.BeliefsDataFrame:
        sensor = tb.Sensor("A")
        beliefs = [
            tb.TimedBelief(
                sensor=sensor,
                event_start=datetime(2023, 1, 1, tzinfo=UTC),
                belief_time=datetime(2023, 1, 1, tzinfo=UTC),
                event_value=1,
                source=s,
            )
            for s in sources
        ]
        bdf = tb.BeliefsDataFrame(beliefs)
        bdf["source.name"] = (
            bdf.index.get_level_values("source").map(lambda x: x.name).values
        )
        bdf["source.model"] = (
            bdf.index.get_level_values("source").map(lambda x: x.model).values
        )
        bdf["source.type"] = (
            bdf.index.get_level_values("source").map(lambda x: x.type).values
        )
        bdf["source.version"] = (
            bdf.index.get_level_values("source").map(lambda x: x.version).values
        )
        return bdf

    # the data source with no version is assumed to have version 0.0.0
    bdf = create_dummy_frame([s1, s2])
    np.testing.assert_array_equal(keep_latest_version(bdf).sources, [s1])

    # sources with different models are preserved
    bdf = create_dummy_frame([s1, s2, s3])
    np.testing.assert_array_equal(keep_latest_version(bdf).sources, [s1, s3])

    # two sources with the same model but different types
    bdf = create_dummy_frame([s3, s4])
    np.testing.assert_array_equal(keep_latest_version(bdf).sources, [s3, s4])
    # also check the reverse order
    bdf = bdf.sort_index(level="source", ascending=False, sort_remaining=False)
    np.testing.assert_array_equal(
        keep_latest_version(bdf).sources,
        [s4, s3],
        "Expected the original order of the data sources to be respected.",
    )

    # two sources with only different IDs (for instance, when they just differ by their data_generator_config)
    bdf = create_dummy_frame([s4, s5])
    np.testing.assert_array_equal(keep_latest_version(bdf).sources, [s5])
    # also check the reverse order
    bdf = bdf.sort_index(level="source", ascending=False, sort_remaining=False)
    np.testing.assert_array_equal(keep_latest_version(bdf).sources, [s5])

    # repeated source
    bdf = create_dummy_frame([s1, s1])
    np.testing.assert_array_equal(keep_latest_version(bdf).sources, [s1])


def test_keep_latest_version_preserves_probabilistic_splits():
    sensor = tb.Sensor("X", event_resolution=timedelta(hours=1))
    s1v1 = DataSource(name="s1", model="model 1", type="forecaster", version="0.1.0")
    s1v2 = DataSource(name="s1", model="model 1", type="forecaster", version="0.2.0")
    # Two probabilistic splits for the same event
    event_start = "2025-10-15T14:00:00+02"
    h = "PT1H"

    def create_bdf(probabilistic_values: list[tuple[float, float]], source: DataSource):
        return tb.BeliefsDataFrame(
            [
                tb.TimedBelief(
                    sensor=sensor,
                    source=source,
                    event_start=event_start,
                    belief_horizon=h,
                    cp=cp,
                    event_value=v,
                )
                for cp, v in probabilistic_values
            ]
        )

    bdf_1 = create_bdf([(0.3, 10.0), (0.7, 20.0)], s1v1)
    # We expect to keep *both* splits (or at least both until further resolution)
    kept = keep_latest_version(bdf_1, one_deterministic_belief_per_event=False)
    # Check that both cumulative probabilities remain
    probs = set(kept.index.get_level_values("cumulative_probability").tolist())
    assert probs == {0.3, 0.7}
    # Also check that two rows survived
    assert len(kept) == 2

    bdf_2 = create_bdf([(0.1, 5.0), (0.5, 16.0), (0.7, 20.2), (0.9, 20.2)], s1v2)
    bdf = pd.concat([bdf_1, bdf_2])
    kept = keep_latest_version(bdf, one_deterministic_belief_per_event=False)
    probs = set(kept.index.get_level_values("cumulative_probability").tolist())
    assert probs == {0.1, 0.5, 0.7, 0.9}  # no more 0.3
    assert len(kept) == 4


def test_get_or_create_source_stable_under_key_order(db, app):
    """get_or_create_source must return the same row regardless of dict key insertion order.

    PostgreSQL JSONB normalises JSON object keys to alphabetical order on every
    round-trip, so a dict like ``{"z": 1, "a": 2}`` comes back as ``{"a": 2, "z": 1}``.
    Before the fix, ``hash_attributes`` used ``json.dumps`` *without* ``sort_keys``,
    meaning the hash of the original dict and the hash of the JSONB-reloaded dict
    differed.  ``get_or_create_source`` then failed to find the existing row and
    silently inserted a duplicate, giving the new row a different ID.  The forecasting
    pipeline stored beliefs under the new ID while the job meta still held the original
    ID, so ``GET /sensors/{id}/forecasts/{uuid}`` returned 400 even though the
    forecasts were present in the database.
    """
    from flexmeasures.data.services.data_sources import get_or_create_source

    # Insert with keys in non-alphabetical insertion order
    attrs_python_order = {"z_last": "value_z", "a_first": "value_a"}
    source_original = get_or_create_source(
        "test-hash-stability",
        source_type="forecaster",
        attributes=attrs_python_order,
    )
    original_id = source_original.id

    # Simulate a JSONB round-trip: PostgreSQL returns keys in alphabetical order
    attrs_jsonb_order = {"a_first": "value_a", "z_last": "value_z"}

    # Before the fix this would create a *new* DataSource with a different ID
    source_via_jsonb = get_or_create_source(
        "test-hash-stability",
        source_type="forecaster",
        attributes=attrs_jsonb_order,
    )

    assert source_via_jsonb.id == original_id, (
        "get_or_create_source created a duplicate DataSource when the same "
        "attributes were supplied in a different key order (as PostgreSQL JSONB "
        "would return them).  Ensure DataSource.hash_attributes uses sort_keys=True."
    )


def test_sensor_data_sources_and_data_source_sensors_load_fast(db, app):
    """Both Sensor.data_sources and DataSource.sensors must stay fast on large tables.

    A previous ORM relationship implementation issued a single JOIN across the full timed_belief table to load either accessor, so its cost grows linearly with the number of belief rows.
    The property implementation instead performs an index-only scan for distinct IDs first, then a tiny primary-key lookup,
    keeping cost proportional to the number of sources/sensors rather than beliefs.

    This test guards bounds on the wall-clock time of both accessors.
    Specifically, the test inserts 100 000 belief rows for one sensor / one source, then asserts both accessors return in under 100 ms.
    That threshold is comfortably met by the two-step subquery but exceeded by the ORM join on any ordinary database server.

    Measured before #2151 (ORM relationship):
        Sensor.data_sources: ~725 ms  →  FAILS
        DataSource.sensors: ~1000 ms  →  FAILS

    Measured after #2151 (two-step subquery property):
        Sensor.data_sources: ~13 ms  →  PASSES
        DataSource.sensors:  ~15 ms  →  PASSES
    """
    THRESHOLD_S = 0.100  # 100 ms — passes with subquery property, fails with ORM join
    N_BELIEFS = 100_000

    # --- minimal schema objects ------------------------------------------------
    asset_type = GenericAssetType(name="perf_test_type")
    db.session.add(asset_type)
    db.session.flush()

    asset = GenericAsset(name="perf_test_asset", generic_asset_type=asset_type)
    db.session.add(asset)
    db.session.flush()

    sensor = Sensor(
        name="perf_test_sensor",
        generic_asset=asset,
        unit="MW",
        event_resolution=timedelta(minutes=15),
    )
    db.session.add(sensor)
    db.session.flush()

    source = DataSource(name="perf_test_source", type="demo script")
    db.session.add(source)
    db.session.flush()

    # --- bulk-insert 100 000 belief rows via Core (fast path) ------------------
    base_dt = datetime(2020, 1, 1, tzinfo=timezone.utc)
    rows = [
        {
            "sensor_id": sensor.id,
            "source_id": source.id,
            "event_start": base_dt + timedelta(minutes=15 * i),
            "belief_horizon": timedelta(0),
            "cumulative_probability": 0.5,
            "event_value": float(i),
        }
        for i in range(N_BELIEFS)
    ]
    db.session.execute(insert(TimedBelief), rows)
    db.session.flush()

    # --- Sensor.data_sources ---------------------------------------------------
    db.session.expire_all()
    t0 = time.perf_counter()
    sources = sensor.data_sources
    elapsed_sensor_data_sources = time.perf_counter() - t0

    assert isinstance(sources, list)
    assert len(sources) == 1
    print(
        f"\nSensor.data_sources ({N_BELIEFS:,} beliefs): "
        f"{elapsed_sensor_data_sources * 1000:.1f} ms"
    )

    # --- DataSource.sensors ----------------------------------------------------
    db.session.expire_all()
    t0 = time.perf_counter()
    sensors = source.sensors
    elapsed_data_source_sensors = time.perf_counter() - t0

    assert isinstance(sensors, list)
    assert len(sensors) == 1
    print(
        f"DataSource.sensors ({N_BELIEFS:,} beliefs): "
        f"{elapsed_data_source_sensors * 1000:.1f} ms"
    )

    assert elapsed_sensor_data_sources < THRESHOLD_S, (
        f"Sensor.data_sources took {elapsed_sensor_data_sources * 1000:.1f} ms "
        f"(limit {THRESHOLD_S * 1000:.0f} ms) — use the two-step subquery property"
    )
    assert elapsed_data_source_sensors < THRESHOLD_S, (
        f"DataSource.sensors took {elapsed_data_source_sensors * 1000:.1f} ms "
        f"(limit {THRESHOLD_S * 1000:.0f} ms) — use the two-step subquery property"
    )


def test_keep_latest_version_equivalence():
    """Compare keep_latest_version against a naive per-row reference implementation."""
    from packaging.version import Version

    def naive_keep_latest_version(
        bdf: tb.BeliefsDataFrame, one_deterministic_belief_per_event: bool
    ) -> tb.BeliefsDataFrame:
        bdf = bdf.loc[~bdf.index.duplicated(keep="first"), :]
        names = list(bdf.index.names)
        event_level = names.index("event_start")
        belief_level = names.index("belief_time")
        source_level = names.index("source")

        def group_key(index_tuple):
            source = index_tuple[source_level]
            key = (index_tuple[event_level], source.name, source.type, source.model)
            if not one_deterministic_belief_per_event:
                key += (index_tuple[belief_level],)
            return key

        winners: dict = {}
        for index_tuple in bdf.index:
            source = index_tuple[source_level]
            key = group_key(index_tuple)
            incumbent = winners.get(key)
            if incumbent is None or (
                Version(source.version or "0.0.0"),
                source.id if source.id is not None else -1,
            ) > (
                Version(incumbent.version or "0.0.0"),
                incumbent.id if incumbent.id is not None else -1,
            ):
                winners[key] = source
        mask = [
            index_tuple[source_level] is winners[group_key(index_tuple)]
            for index_tuple in bdf.index
        ]
        return bdf[mask]

    rng = np.random.default_rng(42)
    sensor = tb.Sensor("equivalence sensor", event_resolution=timedelta(hours=1))
    sources = [
        DataSource(
            id=i + 1 if rng.random() > 0.2 else None,
            name=rng.choice(["s1", "s2"]),
            model=rng.choice(["model 1", "model 2"]),
            type=rng.choice(["forecaster", "scheduler"]),
            version=rng.choice([None, "0.1.0", "0.2.0", "1.0.0"]),
        )
        for i in range(6)
    ]
    event_starts = pd.date_range("2025-01-01", periods=5, freq="1h", tz="UTC")
    belief_times = pd.date_range("2024-12-31", periods=3, freq="1h", tz="UTC")

    for trial in range(10):
        beliefs = []
        for _ in range(rng.integers(2, 20)):
            source = sources[rng.integers(len(sources))]
            cps = [(0.5, float(rng.random()))]
            if rng.random() > 0.7:
                cps = [(0.3, float(rng.random())), (0.7, float(rng.random()))]
            event_start = event_starts[rng.integers(len(event_starts))]
            belief_time = belief_times[rng.integers(len(belief_times))]
            beliefs.extend(
                tb.TimedBelief(
                    sensor=sensor,
                    source=source,
                    event_start=event_start,
                    belief_time=belief_time,
                    cumulative_probability=cp,
                    event_value=value,
                )
                for cp, value in cps
            )
        bdf = tb.BeliefsDataFrame(beliefs)
        for one_deterministic in (False, True):
            result = keep_latest_version(
                bdf, one_deterministic_belief_per_event=one_deterministic
            )
            expected = naive_keep_latest_version(
                bdf, one_deterministic_belief_per_event=one_deterministic
            )
            pd.testing.assert_frame_equal(
                pd.DataFrame(result), pd.DataFrame(expected), check_like=False
            )


def test_get_or_create_source_survives_insert_race(db, app, monkeypatch):
    """Losing an insert race for a new data source must return the winning row.

    On a fresh database, concurrent workers (e.g. running their first-ever
    scheduling jobs) used to be able to insert duplicate DataSource rows,
    because each worker's initial lookup found nothing yet.  We simulate the
    losing worker by patching its initial lookup to find nothing while the row
    actually exists: its INSERT must then hit the DB-level uniqueness index,
    roll back to a savepoint and re-fetch the winner, instead of either
    creating a duplicate or poisoning the session.
    """
    from flexmeasures.data.services import data_sources as data_sources_service
    from flexmeasures.data.services.data_sources import get_or_create_source

    source_info = dict(source_type="scheduler", model="RaceTestScheduler", version="1")
    winner = get_or_create_source("test-race", **source_info)

    real_fetch = data_sources_service.get_first_matching_source
    calls = {"n": 0}

    def miss_on_first_lookup(query):
        calls["n"] += 1
        if calls["n"] == 1:
            # Simulate the race: the other worker's row is not seen by our lookup
            return None
        return real_fetch(query)

    monkeypatch.setattr(
        data_sources_service, "get_first_matching_source", miss_on_first_lookup
    )

    loser = get_or_create_source("test-race", **source_info)

    assert loser.id == winner.id
    assert calls["n"] == 2, "the IntegrityError path should have re-fetched the winner"
    num_sources = db.session.scalar(
        select(func.count())
        .select_from(DataSource)
        .filter_by(
            name="test-race", type="scheduler", model="RaceTestScheduler", version="1"
        )
    )
    assert num_sources == 1, "no duplicate row should have been created"


def test_source_lookups_tolerate_duplicates(db, app):
    """Pre-existing (near-)duplicate sources must not fail lookups with MultipleResultsFound.

    Sources that differ only in their attributes are legitimate separate rows, but a
    lookup that doesn't filter on attributes matches all of them. Such a lookup should
    deterministically return the oldest row instead of raising, so that databases which
    already contain duplicates (created before uniqueness was enforced at the DB level)
    degrade gracefully instead of failing every scheduling job.
    """
    from flexmeasures.data.services.data_sources import get_or_create_source
    from flexmeasures.data.utils import get_data_source

    source_info = dict(source_type="scheduler", model="DupeScheduler", version="2")
    source_1 = get_or_create_source("test-dupes", attributes={"a": 1}, **source_info)
    source_2 = get_or_create_source("test-dupes", attributes={"a": 2}, **source_info)
    assert source_1.id != source_2.id
    oldest_id = min(source_1.id, source_2.id)

    # Lookup without an attributes filter matches both rows; this used to raise
    found = get_or_create_source("test-dupes", **source_info)
    assert found.id == oldest_id

    # Same for the lower-level get_data_source utility
    found = get_data_source(
        "test-dupes",
        data_source_model="DupeScheduler",
        data_source_version="2",
        data_source_type="scheduler",
    )
    assert found.id == oldest_id


def test_exact_duplicate_sources_rejected_by_db(db, app):
    """The DB must reject exact duplicates even when the unique key columns hold NULLs.

    The previous UniqueConstraint was NULL-blind (PostgreSQL treats NULLs as
    distinct), so rows like scheduler sources - which have no user or account -
    could be duplicated freely. The NULL-safe unique index must reject them.
    """
    from sqlalchemy.exc import IntegrityError

    kwargs = dict(name="test-unique", type="scheduler", model="X", version="3")
    db.session.add(DataSource(**kwargs))
    db.session.flush()
    with pytest.raises(IntegrityError):
        with db.session.begin_nested():  # keep the outer transaction usable
            db.session.add(DataSource(**kwargs))
