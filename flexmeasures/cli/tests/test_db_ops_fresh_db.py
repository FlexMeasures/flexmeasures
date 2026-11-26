from datetime import datetime, timedelta

import pandas as pd
import pytest
import timely_beliefs as tb
from pytz import utc
from sqlalchemy import column, inspect, select, table

from flexmeasures.cli.tests.utils import check_command_ran_without_error
from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource, SensorDataSource
from flexmeasures.data.models.time_series import (
    Sensor,
    TimedBelief,
    create_sensor_data_source_trigger,
)
from flexmeasures.data.services import timescaledb
from flexmeasures.data.utils import save_to_db


@pytest.fixture(scope="function")
def plain_timed_belief_afterwards(fresh_db):
    """Give the rest of the test session a plain timed_belief table again, however the test left it.

    The test schema is shared by all tests in a session,
    and there is no way back from a hypertable other than recreating the table.
    Creating one table does not fire the metadata-wide event that installs the sensor_data_source trigger,
    so that is installed here, too.
    """
    yield
    fresh_db.session.rollback()
    with fresh_db.engine.begin() as connection:
        TimedBelief.__table__.drop(bind=connection)
        TimedBelief.__table__.create(bind=connection)
        create_sensor_data_source_trigger(None, connection)


@pytest.fixture(scope="function")
def timescaledb_server(fresh_db):
    """Skip the test unless the test database server provides TimescaleDB."""
    if timescaledb.available_version(fresh_db.session) is None:
        pytest.skip("The test database server does not provide TimescaleDB.")


def _search(sensor_id: int) -> pd.DataFrame:
    return TimedBelief.search(
        sensor_id, event_starts_after=datetime(2023, 4, 1, tzinfo=utc)
    ).sort_index()


def _save_belief(
    sensor_id: int, source: DataSource, event_start: datetime, value: float
):
    """Save one belief, formed a day before the event, as the dummy data's beliefs are."""
    save_to_db(
        tb.BeliefsDataFrame(
            pd.DataFrame(
                dict(
                    event_start=[event_start],
                    belief_time=[datetime(2023, 4, 9, tzinfo=utc)],
                    event_value=[value],
                    source=[source],
                )
            ),
            sensor=db.session.get(Sensor, sensor_id),
        )
    )


def _chunk_time_interval(session) -> timedelta:
    dimensions = table(
        "dimensions",
        column("hypertable_name"),
        column("time_interval"),
        schema="timescaledb_information",
    )
    return session.execute(
        select(dimensions.c.time_interval).where(
            dimensions.c.hypertable_name == timescaledb.TABLE
        )
    ).scalar_one()


def _index_names(engine) -> set[str]:
    return {index["name"] for index in inspect(engine).get_indexes("timed_belief")}


def test_enable_timescaledb(
    app,
    fresh_db,
    setup_dummy_data_fresh_db,
    timescaledb_server,
    plain_timed_belief_afterwards,
    monkeypatch,
):
    """Converting to a compressed hypertable changes how beliefs are stored, but not what queries return or whether they can be written."""
    from flexmeasures.cli.db_ops import enable_timescaledb

    sensor_id = setup_dummy_data_fresh_db[0]
    before = _search(sensor_id)
    assert len(before) == 200

    # The 200 hourly beliefs span 9 days, so daily chunks give several.
    # They are all from 2023, so compression after the default 30 days takes every chunk.
    result = app.test_cli_runner().invoke(
        enable_timescaledb, ["--force", "--chunk-time-interval", "1 day"]
    )
    check_command_ran_without_error(result)
    assert "Compressed 9 chunk(s) older than 30 days." in result.output
    assert timescaledb.is_hypertable(fresh_db.session)
    assert timescaledb.count_chunks(fresh_db.session) == 9
    assert timescaledb.compression_policy_age(fresh_db.session) == "30 days"
    # Only the indexes the data model declares, so `flexmeasures db migrate` has nothing to propose dropping.
    assert _index_names(fresh_db.engine) == {
        index.name for index in TimedBelief.__table__.indexes
    }
    pd.testing.assert_frame_equal(_search(sensor_id), before)

    # Running it again with the same age compresses nothing more, and says so.
    result = app.test_cli_runner().invoke(
        enable_timescaledb, ["--force", "--compress-after", "30 days"]
    )
    check_command_ran_without_error(result)
    assert "Compressed 0 chunk(s)" in result.output

    # Running it again with another age changes the policy, too.
    result = app.test_cli_runner().invoke(
        enable_timescaledb, ["--force", "--compress-after", "60 days"]
    )
    check_command_ran_without_error(result)
    assert timescaledb.compression_policy_age(fresh_db.session) == "60 days"

    # Running it again with another chunk time interval applies it to new chunks.
    result = app.test_cli_runner().invoke(
        enable_timescaledb, ["--force", "--chunk-time-interval", "2 days"]
    )
    check_command_ran_without_error(result)
    assert "existing chunks keep theirs" in result.output
    assert _chunk_time_interval(fresh_db.session) == timedelta(days=2)
    assert timescaledb.count_chunks(fresh_db.session) == 9
    pd.testing.assert_frame_equal(_search(sensor_id), before)

    # Compressed chunks still take late beliefs,
    # and the trigger that records which sources have data on which sensors still sees them.
    new_source = DataSource("source2")
    _save_belief(sensor_id, new_source, datetime(2023, 4, 10, tzinfo=utc), -1.0)
    fresh_db.session.commit()
    after = _search(sensor_id)
    assert len(after) == 201
    assert after.xs(new_source, level="source")["event_value"].item() == -1.0
    assert fresh_db.session.execute(
        select(SensorDataSource).filter_by(sensor_id=sensor_id, source_id=new_source.id)
    ).scalar_one_or_none()

    # And they take overwrites (upserts) of beliefs they hold.
    monkeypatch.setitem(app.config, "FLEXMEASURES_ALLOW_DATA_OVERWRITE", True)
    old_source = fresh_db.session.execute(
        select(DataSource).filter_by(name="source1")
    ).scalar_one()
    _save_belief(sensor_id, old_source, datetime(2023, 4, 10, tzinfo=utc), 1000.0)
    fresh_db.session.commit()
    after = _search(sensor_id)
    assert len(after) == 201
    assert after.xs(old_source, level="source")["event_value"].iloc[0] == 1000.0


def test_enable_timescaledb_without_timescaledb(
    app, fresh_db, setup_dummy_data_fresh_db, monkeypatch
):
    """On a server without TimescaleDB, the command says so and leaves the table alone."""
    from flexmeasures.cli.db_ops import enable_timescaledb

    monkeypatch.setattr(timescaledb, "installed_version", lambda session: None)
    monkeypatch.setattr(timescaledb, "available_version", lambda session: None)

    result = app.test_cli_runner().invoke(enable_timescaledb, ["--force"])

    assert result.exit_code != 0
    assert "does not provide the timescaledb extension" in result.output
    assert len(_search(setup_dummy_data_fresh_db[0])) == 200


def test_enable_timescaledb_needs_2_18(app, fresh_db, monkeypatch):
    """Hypertables accept the transition table of the sensor_data_source trigger only from TimescaleDB 2.18 on."""
    from flexmeasures.cli.db_ops import enable_timescaledb

    monkeypatch.setattr(timescaledb, "installed_version", lambda session: "2.17.2")

    result = app.test_cli_runner().invoke(enable_timescaledb, ["--force"])

    assert result.exit_code != 0
    assert (
        "TimescaleDB 2.17.2 is installed, but at least 2.18 is needed" in result.output
    )


@pytest.mark.parametrize(
    "mode, edition_compresses, message",
    [
        ("play", True, "This is a play server"),
        ("", False, "Apache-licensed edition of TimescaleDB, which cannot compress"),
    ],
)
def test_enable_timescaledb_refuses(
    app, fresh_db, monkeypatch, mode, edition_compresses, message
):
    """Converting is refused on a play server (unless forced), and on a TimescaleDB edition without compression."""
    from flexmeasures.cli.db_ops import enable_timescaledb

    monkeypatch.setitem(app.config, "FLEXMEASURES_MODE", mode)
    monkeypatch.setattr(timescaledb, "ensure_extension", lambda session: "2.22.1")
    monkeypatch.setattr(timescaledb, "installed_version", lambda session: None)
    monkeypatch.setattr(
        timescaledb, "supports_compression", lambda session: edition_compresses
    )
    converted = []
    monkeypatch.setattr(
        timescaledb,
        "convert_to_hypertable",
        lambda *args: converted.append(args),
    )

    result = app.test_cli_runner().invoke(enable_timescaledb, ["--no-force"])

    assert result.exit_code != 0
    assert message in result.output
    assert not converted
