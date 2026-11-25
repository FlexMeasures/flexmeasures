from datetime import datetime, timedelta

import pandas as pd
import pytest
import timely_beliefs as tb
from pytz import utc
from sqlalchemy import inspect, select

from flexmeasures.cli.tests.utils import check_command_ran_without_error
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


def _search(sensor_id: int) -> pd.DataFrame:
    return TimedBelief.search(
        sensor_id, event_starts_after=datetime(2023, 4, 1, tzinfo=utc)
    ).sort_index()


def test_enable_timescaledb(
    app, fresh_db, setup_dummy_data_fresh_db, plain_timed_belief_afterwards
):
    """Converting to a hypertable and compressing it changes how beliefs are stored, but not what queries return or whether they can be updated."""
    if timescaledb.available_version(fresh_db.session) is None:
        pytest.skip("The test database server does not provide TimescaleDB.")
    from flexmeasures.cli.db_ops import enable_timescaledb

    sensor_id = setup_dummy_data_fresh_db[0]
    before = _search(sensor_id)
    assert len(before) == 200

    # The 200 hourly beliefs span 9 days, so daily chunks give several.
    result = app.test_cli_runner().invoke(
        enable_timescaledb, ["--yes", "--chunk-time-interval", "1 day"]
    )
    check_command_ran_without_error(result)
    assert timescaledb.is_hypertable(fresh_db.session)
    assert timescaledb.count_chunks(fresh_db.session) == 9
    # Only the indexes the data model declares, so `flexmeasures db migrate` has nothing to propose dropping.
    assert {
        index["name"] for index in inspect(fresh_db.engine).get_indexes("timed_belief")
    } == {index.name for index in TimedBelief.__table__.indexes}
    pd.testing.assert_frame_equal(_search(sensor_id), before)

    # Running it again only applies compression; all beliefs are from 2023, so every chunk qualifies.
    result = app.test_cli_runner().invoke(
        enable_timescaledb, ["--yes", "--compress-after", "1 day"]
    )
    check_command_ran_without_error(result)
    assert "already a hypertable" in result.output
    assert "Compressed 9 chunk(s)" in result.output
    pd.testing.assert_frame_equal(_search(sensor_id), before)

    # Compressed chunks still take new beliefs,
    # and the trigger that records which sources have data on which sensors still sees them.
    sensor = fresh_db.session.get(Sensor, sensor_id)
    new_source = DataSource("source2")
    event_start = datetime(2023, 4, 10, tzinfo=utc)
    save_to_db(
        tb.BeliefsDataFrame(
            pd.DataFrame(
                dict(
                    event_start=[event_start],
                    belief_time=[event_start + timedelta(days=1)],
                    event_value=[-1.0],
                    source=[new_source],
                )
            ),
            sensor=sensor,
        )
    )
    fresh_db.session.commit()
    after = _search(sensor_id)
    assert len(after) == 201
    assert after.xs(new_source, level="source")["event_value"].item() == -1.0
    assert fresh_db.session.execute(
        select(SensorDataSource).filter_by(sensor_id=sensor_id, source_id=new_source.id)
    ).scalar_one_or_none()


def test_enable_timescaledb_without_timescaledb(
    app, fresh_db, setup_dummy_data_fresh_db, monkeypatch
):
    """On a server without TimescaleDB, the command says so and leaves the table alone."""
    from flexmeasures.cli.db_ops import enable_timescaledb

    monkeypatch.setattr(timescaledb, "installed_version", lambda session: None)
    monkeypatch.setattr(timescaledb, "available_version", lambda session: None)

    result = app.test_cli_runner().invoke(enable_timescaledb, ["--yes"])

    assert result.exit_code != 0
    assert "does not provide the timescaledb extension" in result.output
    assert len(_search(setup_dummy_data_fresh_db[0])) == 200
