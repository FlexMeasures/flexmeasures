"""Tests for the sensor_data_source summary table."""

from pathlib import Path

import pandas as pd
from sqlalchemy import func, select
from timely_beliefs import BeliefsDataFrame

from flexmeasures.data.models.data_sources import DataSource, SensorDataSource
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.utils import save_to_db
from flexmeasures.tests.utils import get_test_sensor


def pairs(db) -> set:
    return set(
        db.session.execute(
            select(SensorDataSource.sensor_id, SensorDataSource.source_id)
        ).all()
    )


def make_belief(sensor, source, hours_offset: int = 0) -> BeliefsDataFrame:
    return BeliefsDataFrame(
        [
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=pd.Timestamp("2021-03-28 16:00:00+00:00")
                + pd.Timedelta(hours=hours_offset),
                belief_time=pd.Timestamp("2021-03-27 08:00:00+00:00"),
                event_value=1.0,
            )
        ]
    )


def test_saving_beliefs_records_the_pair(setup_beliefs, db):
    """Saving beliefs must record which source recorded for which sensor."""
    sensor = get_test_sensor(db)
    source = DataSource(name="Association test source", type="demo script")
    db.session.add(source)
    db.session.commit()

    assert (sensor.id, source.id) not in pairs(db)

    save_to_db(make_belief(sensor, source))
    db.session.commit()

    assert (sensor.id, source.id) in pairs(db)


def test_inserts_that_bypass_the_save_path_still_record_the_pair(setup_beliefs, db):
    """A raw insert must maintain the summary just as a normal save does.

    This is the case that decided the design.
    Beliefs reach timed_belief by more routes than ``save_to_db``:
    bulk inserts, plugins and raw SQL among them, and several of this repo's own fixtures.
    A hook in the save path would leave the summary silently incomplete for all of them,
    so a database trigger maintains it instead.
    """
    sensor = get_test_sensor(db)
    source = DataSource(name="Raw insert source", type="demo script")
    db.session.add(source)
    db.session.commit()

    db.session.execute(
        TimedBelief.__table__.insert().values(
            sensor_id=sensor.id,
            source_id=source.id,
            event_start=pd.Timestamp("2021-03-28 20:00:00+00:00"),
            belief_horizon=pd.Timedelta(hours=1),
            cumulative_probability=0.5,
            event_value=3.0,
        )
    )
    db.session.commit()

    assert (sensor.id, source.id) in pairs(db)
    assert sensor in source.sensors


def test_recording_the_pair_is_idempotent(setup_beliefs, db):
    """Saving more beliefs from the same source must not raise or duplicate."""
    sensor = get_test_sensor(db)
    source = DataSource(name="Idempotent source", type="demo script")
    db.session.add(source)
    db.session.commit()

    save_to_db(make_belief(sensor, source, hours_offset=0))
    db.session.commit()
    save_to_db(make_belief(sensor, source, hours_offset=1))
    db.session.commit()

    matching = [p for p in pairs(db) if p == (sensor.id, source.id)]
    assert len(matching) == 1


def test_accessors_read_the_summary_and_not_the_beliefs(setup_beliefs, db):
    """Both accessors must answer from sensor_data_source, not from timed_belief.

    Shown by writing a pair into the summary for which no belief exists at all.
    An accessor reading timed_belief could not return it;
    one reading the summary must.
    """
    sensor = get_test_sensor(db)
    source = DataSource(name="Source with no beliefs at all", type="demo script")
    db.session.add(source)
    db.session.commit()

    assert sensor not in source.sensors
    assert source not in sensor.data_sources

    db.session.add(SensorDataSource(sensor_id=sensor.id, source_id=source.id))
    db.session.commit()

    # No belief ties these two together, so only the summary can be the answer's source.
    belief_count = db.session.execute(
        select(func.count())
        .select_from(TimedBelief)
        .where(TimedBelief.sensor_id == sensor.id, TimedBelief.source_id == source.id)
    ).scalar()
    assert belief_count == 0

    assert sensor in source.sensors
    assert source in sensor.data_sources


def test_data_source_sensors_reflects_a_saved_belief(setup_beliefs, db):
    """Saving a belief must make the sensor show up on the source."""
    sensor = get_test_sensor(db)
    source = DataSource(name="Source listing sensors", type="demo script")
    db.session.add(source)
    db.session.commit()

    assert sensor not in source.sensors

    save_to_db(make_belief(sensor, source))
    db.session.commit()

    assert sensor in source.sensors


def test_sensor_data_sources_reflects_a_saved_belief(setup_beliefs, db):
    """Saving a belief must make the source show up on the sensor, mirroring the above."""
    sensor = get_test_sensor(db)
    source = DataSource(name="Source found from sensor", type="demo script")
    db.session.add(source)
    db.session.commit()

    save_to_db(make_belief(sensor, source))
    db.session.commit()

    assert source in sensor.data_sources


def test_summary_is_a_superset_after_deleting_beliefs(setup_beliefs, db):
    """A pair survives deletion of the beliefs that created it, by design.

    Deciding whether a pair went stale would need the scan over timed_belief that this table exists to avoid,
    so the summary is deliberately a superset.
    This test pins that, so the behaviour is a documented choice rather than a surprise.
    """
    sensor = get_test_sensor(db)
    source = DataSource(name="Source whose beliefs go away", type="demo script")
    db.session.add(source)
    db.session.commit()

    save_to_db(make_belief(sensor, source))
    db.session.commit()
    assert (sensor.id, source.id) in pairs(db)

    db.session.execute(
        TimedBelief.__table__.delete().where(
            TimedBelief.source_id == source.id, TimedBelief.sensor_id == sensor.id
        )
    )
    db.session.commit()

    assert (sensor.id, source.id) in pairs(db), "pair should survive, by design"
    assert sensor in source.sensors


def test_time_filtered_source_search_still_reads_beliefs(setup_beliefs, db):
    """With time filters, the answer must stay exact rather than use the summary.

    The summary knows nothing about when beliefs were recorded,
    so a time-bounded question has to go to timed_belief.
    If it did not, a source whose beliefs all fall outside the window would be wrongly reported.
    """
    sensor = get_test_sensor(db)
    source = DataSource(name="Source outside the window", type="demo script")
    db.session.add(source)
    db.session.commit()

    save_to_db(make_belief(sensor, source))
    db.session.commit()

    # Unfiltered: found via the summary
    assert source in sensor.search_data_sources()

    # Filtered to a window containing no beliefs from this source: must not appear
    found = sensor.search_data_sources(
        event_starts_after=pd.Timestamp("2030-01-01 00:00:00+00:00")
    )
    assert source not in found


def test_migration_installs_the_same_trigger_definition():
    """Migration f1c8a3d75e29 must not carry its own copy of the trigger's SQL.

    A second copy could drift from flexmeasures.data.models.time_series without
    anyone noticing, which is exactly the kind of divergence between a migrated
    database and one built by create_all() this table's design is meant to avoid.
    Importing the same constants makes such drift structurally impossible,
    rather than merely unlikely; this test only guards against the import being
    replaced by a fresh copy-paste later on.
    """
    import importlib.util

    from flexmeasures.data.models import time_series

    spec = importlib.util.spec_from_file_location(
        "f1c8a3d75e29",
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "f1c8a3d75e29_add_sensor_data_source_table.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.RECORD_SENSOR_DATA_SOURCES_FUNCTION is (
        time_series.RECORD_SENSOR_DATA_SOURCES_FUNCTION
    )
    assert migration.RECORD_SENSOR_DATA_SOURCES_TRIGGER is (
        time_series.RECORD_SENSOR_DATA_SOURCES_TRIGGER
    )
