"""Check that duplicate source ranking reads beliefs through their sensor/source key."""

from importlib import import_module

import pytest

from sqlalchemy import text

from flexmeasures.data.models.data_sources import DATA_SOURCE_UNIQUE_INDEX, DataSource
from flexmeasures.data.services.data_sources import find_duplicate_sources


def test_duplicate_source_ranking(fresh_db, setup_markets_fresh_db):
    sensor = setup_markets_fresh_db["epex_da"]
    migration = import_module(
        "flexmeasures.data.migrations.versions."
        "7c4e1a9d2b58_refuse_duplicate_data_sources"
    )

    # The migration runs before this index exists. Roll back the savepoint to restore
    # the test schema after inserting duplicates that the current schema refuses.
    savepoint = fresh_db.session.begin_nested()
    try:
        fresh_db.session.execute(text(f"DROP INDEX {DATA_SOURCE_UNIQUE_INDEX}"))
        sources = [DataSource(name="same", type="scheduler") for _ in range(3)] + [
            DataSource(name="other", type="scheduler"),
            DataSource(name="without-beliefs", type="scheduler"),
            DataSource(name="without-beliefs", type="scheduler"),
        ]
        fresh_db.session.add_all(sources)
        fresh_db.session.flush()

        for source, event_start in (
            (sources[1], "2026-01-02"),
            (sources[2], "2026-01-03"),
            (sources[3], "2026-01-04"),
        ):
            fresh_db.session.execute(
                text("""
                    INSERT INTO timed_belief
                        (sensor_id, source_id, event_start, belief_horizon,
                         cumulative_probability, event_value)
                    VALUES (:sensor_id, :source_id, :event_start, INTERVAL '1 day',
                            0.5, 1)
                """),
                {
                    "sensor_id": sensor.id,
                    "source_id": source.id,
                    "event_start": event_start,
                },
            )

        expected = {
            sources[0].id: sources[2].id,
            sources[1].id: sources[2].id,
            sources[5].id: sources[4].id,
        }
        assert find_duplicate_sources() == expected
        assert (
            migration.merge_duplicate_sources(fresh_db.session.connection()) == expected
        )
    finally:
        savepoint.rollback()


def _duplicate_source_migration():
    return import_module(
        "flexmeasures.data.migrations.versions."
        "7c4e1a9d2b58_refuse_duplicate_data_sources"
    )


def test_a_named_source_keeps_its_id():
    """Naming a source of a group of duplicates keeps that one, and merges the others into it."""
    apply_named_keepers = _duplicate_source_migration()._apply_named_keepers

    assert apply_named_keepers({2: 1, 3: 1}, {3: 3}) == {1: 3, 2: 3}
    assert apply_named_keepers({2: 1, 3: 1}, {1: 1}) == {2: 1, 3: 1}
    # A named source that has no duplicates changes nothing.
    assert apply_named_keepers({2: 1, 3: 1}, {9: 9}) == {2: 1, 3: 1}


@pytest.mark.parametrize("named", [(2, 3), (1, 3)])
def test_naming_two_sources_of_one_group_is_refused(named):
    """A group of duplicates keeps one ID, so naming two of its sources is a contradiction, refused before anything is merged."""
    apply_named_keepers = _duplicate_source_migration()._apply_named_keepers

    with pytest.raises(RuntimeError, match=" and ".join(str(n) for n in named)):
        apply_named_keepers({2: 1, 3: 1}, {n: n for n in named})
