"""Check that duplicate source ranking reads beliefs through their sensor/source key."""

from importlib import import_module

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
