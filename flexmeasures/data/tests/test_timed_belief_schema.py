"""Tests for the shape of the timed_belief table itself.

Needs no database: these inspect the mapped table's metadata.
"""

from flexmeasures.data.models.time_series import TimedBelief

#: Must match the column order created by the ``d4a7c1e93b52`` migration.
EXPECTED_PRIMARY_KEY_ORDER = [
    "sensor_id",
    "source_id",
    "event_start",
    "belief_horizon",
    "cumulative_probability",
]


def test_primary_key_column_order_is_pinned():
    """The primary key's column order must be deliberate, not incidental.

    Without an explicit PrimaryKeyConstraint,
    the order is whatever order SQLAlchemy collected the columns in,
    which depends on which columns this class and timely_beliefs' mixin each declare.
    Adding or moving a column override silently reshapes the key,
    and a create_all() schema then disagrees with a migrated one.
    This test is what stops that happening unnoticed.
    """
    assert [
        column.name for column in TimedBelief.__table__.primary_key.columns
    ] == EXPECTED_PRIMARY_KEY_ORDER


def test_sensor_and_source_are_adjacent_in_the_primary_key():
    """Keeping the two 4-byte integer columns adjacent avoids alignment padding.

    Separating them pads every index tuple out by 8 bytes,
    which measured at roughly 15% of the index's total size.
    """
    names = [column.name for column in TimedBelief.__table__.primary_key.columns]
    assert abs(names.index("sensor_id") - names.index("source_id")) == 1


def test_sensor_id_leads_the_primary_key():
    """Nearly every query filters on a single sensor.

    A primary key that does not lead with sensor_id cannot serve those queries,
    which is what made a separate sensor-leading composite index necessary.
    """
    names = [column.name for column in TimedBelief.__table__.primary_key.columns]
    assert names[0] == "sensor_id"


def test_timely_beliefs_search_indexes_are_still_present():
    """Pinning the primary key must not drop the mixin's indexes."""
    index_names = {index.name for index in TimedBelief.__table__.indexes}
    for suffix in ("search_session_idx", "search_session_singleevent_idx"):
        assert any(
            name.endswith(suffix) for name in index_names
        ), f"timely_beliefs' {suffix} went missing: {sorted(index_names)}"


def test_no_redundant_single_column_indexes():
    """No single-column index may duplicate a composite index's leading column.

    A single-column index on event_start or sensor_id is fully covered by the composite indexes timely_beliefs declares,
    so it only costs storage on our largest table,
    and slows every write that has to maintain it.
    Migration ``b7e5a2c40f18`` drops them from existing databases;
    this keeps the ORM from declaring them again (it needs timely-beliefs >= 4.2.0).
    """
    single_column = {
        index.name for index in TimedBelief.__table__.indexes if len(index.columns) == 1
    }
    assert not single_column, f"redundant single-column indexes: {single_column}"


def test_dropped_index_columns_still_lead_a_composite_index():
    """Both columns we stopped indexing individually must still lead a composite.

    event_start carries time-range scans,
    and sensor_id additionally backs the ON DELETE CASCADE from the sensor table:
    PostgreSQL can use a composite index for that only while the column leads it.
    """
    leading = {list(index.columns)[0].name for index in TimedBelief.__table__.indexes}
    for column_name in ("event_start", "sensor_id"):
        assert column_name in leading, (
            f"{column_name} no longer leads any index, so dropping its "
            f"single-column index is no longer safe: {sorted(leading)}"
        )
