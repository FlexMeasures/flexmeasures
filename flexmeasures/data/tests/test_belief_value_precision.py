"""Tests for storing belief values at single precision (float4).

See the column overrides on flexmeasures.data.models.time_series.TimedBelief and the
``9f2c1d7b3a44`` migration.
"""

import pandas as pd
import pytest
from sqlalchemy import Float
from timely_beliefs import BeliefsDataFrame

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.services.sensors import get_sensor_stats
from flexmeasures.data.services.time_series import round_to_stored_precision
from flexmeasures.data.utils import save_to_db
from flexmeasures.tests.utils import get_test_sensor


@pytest.mark.parametrize("column_name", ["cumulative_probability", "event_value"])
def test_value_columns_are_single_precision(column_name):
    """The two value columns must be declared as float4, not float8.

    This is what the ``9f2c1d7b3a44`` migration puts in the database, so the ORM has to
    agree -- otherwise a schema built by create_all() (as the test suite does) silently
    diverges from every migrated deployment. It also guards against a future
    timely_beliefs release quietly reclaiming these columns.
    """
    column = TimedBelief.__table__.columns[column_name]
    assert isinstance(column.type, Float)
    assert column.type.precision == 24, (
        f"{column_name} is no longer declared as float4 "
        f"(precision={column.type.precision})"
    )


def test_rounding_follows_the_column_rather_than_a_hardcoded_precision(monkeypatch):
    """No rounding may happen while the column is still float8.

    There is a window between deploying this code and running the ``9f2c1d7b3a44``
    migration in which the column is still double precision. Rounding to float4 during
    that window would classify a genuine update as "unchanged" and silently drop it, so
    the precision has to be read from the column rather than assumed.
    """
    from flexmeasures.data.services import time_series as time_series_service

    # Pretend the column is still double precision, as it is pre-migration
    monkeypatch.setattr(time_series_service, "_stored_dtype", lambda field: None)

    high_precision_value = 1234567.891
    df = pd.DataFrame(
        {"event_value": [high_precision_value], "cumulative_probability": [0.5]}
    )
    rounded = time_series_service.round_to_stored_precision(df)

    assert (
        rounded["event_value"][0] == high_precision_value
    ), "values were rounded even though the column is not narrowed"


def test_stored_dtype_reads_the_mapped_column():
    """The stored dtype must be derived from the column, and be float32 today."""
    from flexmeasures.data.services.time_series import _stored_dtype

    _stored_dtype.cache_clear()
    assert _stored_dtype("event_value") == "float32"
    assert _stored_dtype("cumulative_probability") == "float32"


def test_round_to_stored_precision_leaves_input_untouched():
    """The helper must not mutate the frame it is handed."""
    df = pd.DataFrame(
        {"event_value": [1234567.891], "cumulative_probability": [0.5], "other": [1.0]}
    )
    rounded = round_to_stored_precision(df)

    assert df["event_value"][0] == 1234567.891, "input frame was mutated"
    assert rounded["event_value"][0] != 1234567.891, "value was not rounded"
    assert rounded["event_value"][0] == pytest.approx(1234567.891, rel=1e-6)
    # Columns that are not stored as float4 must pass through untouched
    assert rounded["other"][0] == 1.0


def test_resubmitting_a_high_precision_value_is_dropped_as_unchanged(setup_beliefs, db):
    """Re-submitting a value needing more than float4 precision must be a no-op.

    The database rounds the stored value to float4, so a candidate carrying the original
    double-precision value no longer compares equal to it. Without rounding the
    comparison to the precision the value is actually stored at, the candidate looks
    like a changed belief on every submission -- and since its belief time is unchanged
    too, saving it raises a duplicate key violation instead of being quietly skipped.
    """
    sensor = get_test_sensor(db)
    source = DataSource(name="High precision source", type="demo script")
    db.session.add(source)
    db.session.commit()

    event_start = pd.Timestamp("2021-03-28 16:00:00+00:00")
    belief_time = pd.Timestamp("2021-03-27 08:00:00+00:00")
    # Needs 10 significant digits, so float4 (~7) cannot represent it exactly
    high_precision_value = 1234567.891
    assert float(pd.Series([high_precision_value]).astype("float32")[0]) != (
        high_precision_value
    ), "test value is representable in float4, so it proves nothing"

    def candidate() -> BeliefsDataFrame:
        return BeliefsDataFrame(
            [
                TimedBelief(
                    sensor=sensor,
                    source=source,
                    event_start=event_start,
                    belief_time=belief_time,
                    event_value=high_precision_value,
                )
            ]
        )

    save_to_db(candidate())
    db.session.commit()
    num_beliefs = len(sensor.search_beliefs(most_recent_beliefs_only=False))

    # Submitting the very same value again must not raise, and must not store anything
    save_to_db(candidate())
    db.session.commit()

    assert len(sensor.search_beliefs(most_recent_beliefs_only=False)) == num_beliefs


def test_sum_over_values_does_not_accumulate_in_single_precision(setup_beliefs, db):
    """Sensor stats must sum in double precision, even though values are stored float4.

    PostgreSQL's ``sum(real)`` accumulates in ``real``. Once the running total reaches
    2^24, adding 1 to it is a no-op, so a sum over many rows silently loses whole units.
    Both values used here are exactly representable in float4, so any error observed is
    the accumulator's, not the storage's.
    """
    sensor = get_test_sensor(db)
    source = DataSource(name="Accumulator source", type="demo script")
    db.session.add(source)
    db.session.commit()

    large_value = 2.0**24  # 16777216, where the float4 gap between values is 2
    num_ones = 100
    belief_time = pd.Timestamp("2021-03-27 08:00:00+00:00")
    event_start = pd.Timestamp("2021-03-28 16:00:00+00:00")

    beliefs = [
        TimedBelief(
            sensor=sensor,
            source=source,
            event_start=event_start + pd.Timedelta(hours=i),
            belief_time=belief_time,
            event_value=large_value if i == 0 else 1.0,
        )
        for i in range(num_ones + 1)
    ]
    save_to_db(BeliefsDataFrame(beliefs))
    db.session.commit()

    stats = get_sensor_stats(sensor, "", "", from_cache=False)
    our_stats = [v for k, v in stats.items() if f"(ID: {source.id})" in k]
    assert len(our_stats) == 1, f"expected one row for our source, got {stats.keys()}"

    # Accumulating in float4 would return large_value, having dropped every single 1.0
    assert our_stats[0]["Sum over values"] == pytest.approx(
        large_value + num_ones, abs=0.5
    )
