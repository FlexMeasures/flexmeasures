"""Optional TimescaleDB support for the timed_belief table.

FlexMeasures runs on plain PostgreSQL, and nothing here is needed for it to work.
Hosts whose PostgreSQL server ships TimescaleDB can convert timed_belief into a hypertable,
partitioned into time chunks on event_start,
and optionally compress chunks once they are old enough.
Queries do not change: a hypertable is still a table to SQLAlchemy and to timely-beliefs.

This is deliberately an explicit operation (see ``flexmeasures db-ops enable-timescaledb``),
not a migration.
TimescaleDB's own Docker images install the extension into every new database,
so the extension being present says nothing about whether a host chose this.
And converting a populated table moves every row into chunks under a lock that blocks writes,
which no host should get as a side effect of a routine ``flexmeasures db upgrade``.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

TABLE = "timed_belief"
PARTITION_COLUMN = "event_start"

#: ``by_range`` (the dimension-builder form of create_hypertable) arrived in TimescaleDB 2.13.
MINIMUM_VERSION = (2, 13)

#: Compressed chunks are stored per segment, and nearly every query asks for one sensor (and often one source),
#: so segmenting by those lets a query decompress only the segments it needs.
COMPRESS_SEGMENT_BY = "sensor_id, source_id"
#: The rest of the primary key orders the rows within a segment,
#: so that time-range filters can skip compressed batches, and so that upserts find their conflicts cheaply.
COMPRESS_ORDER_BY = "event_start, belief_horizon, cumulative_probability"


class TimescaleDBUnavailable(Exception):
    """The database server cannot run TimescaleDB, or runs a version that is too old."""


def installed_version(session: Session) -> str | None:
    """Return the TimescaleDB version installed in this database, or None if it is not installed."""
    return session.execute(
        text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
    ).scalar_one_or_none()


def available_version(session: Session) -> str | None:
    """Return the TimescaleDB version the server could install, or None if it has none."""
    return session.execute(
        text(
            "SELECT default_version FROM pg_available_extensions WHERE name = 'timescaledb'"
        )
    ).scalar_one_or_none()


def _parse_version(version: str) -> tuple[int, ...]:
    """Turn e.g. '2.22.1' into (2, 22, 1), ignoring any suffix such as '-dev'."""
    return tuple(int(part) for part in version.split("-")[0].split("."))


def ensure_extension(session: Session) -> str:
    """Install the TimescaleDB extension in this database if needed, and return its version.

    Installing needs the server to preload the library (``shared_preload_libraries = 'timescaledb'``),
    and a role that may create extensions.
    Errors from the server about either are left to propagate, as they say what is wrong better than we could.
    """
    version = installed_version(session)
    if version is None:
        if available_version(session) is None:
            raise TimescaleDBUnavailable(
                "This PostgreSQL server does not provide the timescaledb extension."
            )
        session.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        version = installed_version(session)
    if _parse_version(version) < MINIMUM_VERSION:
        raise TimescaleDBUnavailable(
            f"TimescaleDB {version} is installed, but at least {'.'.join(map(str, MINIMUM_VERSION))} is needed."
        )
    return version


def is_hypertable(session: Session) -> bool:
    """Whether timed_belief (as resolved via the search path) is already a hypertable."""
    if installed_version(session) is None:
        return False
    return (
        session.execute(
            text(
                "SELECT 1 FROM timescaledb_information.hypertables h"
                " WHERE format('%I.%I', h.hypertable_schema, h.hypertable_name)::regclass"
                " = CAST(:table AS regclass)"
            ),
            dict(table=TABLE),
        ).first()
        is not None
    )


def convert_to_hypertable(session: Session, chunk_time_interval: str) -> None:
    """Convert timed_belief into a hypertable, moving any existing rows into chunks.

    The primary key already contains event_start, which TimescaleDB requires of every unique index.
    TimescaleDB's default index on the partition column is not created:
    the existing indexes cover it,
    and an index that the data model does not declare would make ``flexmeasures db migrate`` propose dropping it.

    :param chunk_time_interval: how much event time each chunk spans, as a PostgreSQL interval (e.g. '7 days').
                                Aim for the most recent chunks (with their indexes) to fit in memory.
    """
    session.execute(
        text(
            "SELECT create_hypertable("
            " CAST(:table AS regclass),"
            " by_range(:column, CAST(:interval AS interval)),"
            " create_default_indexes => false,"
            " migrate_data => true"
            ")"
        ),
        dict(table=TABLE, column=PARTITION_COLUMN, interval=chunk_time_interval),
    )
    # The rows now live in fresh chunk tables, which have no planner statistics yet.
    session.execute(text(f"ANALYZE {TABLE}"))


def enable_compression(session: Session, compress_after: str) -> None:
    """Compress chunks whose events are all older than ``compress_after``, now and from now on.

    TimescaleDB runs the policy as a background job.
    Compressed chunks still accept inserts, updates, upserts and deletes,
    but these are slower than on uncompressed chunks,
    so pick an age beyond which data is rarely rewritten.

    :param compress_after: a PostgreSQL interval (e.g. '30 days').
    """
    session.execute(
        text(
            f"ALTER TABLE {TABLE} SET ("
            " timescaledb.compress,"
            f" timescaledb.compress_segmentby = '{COMPRESS_SEGMENT_BY}',"
            f" timescaledb.compress_orderby = '{COMPRESS_ORDER_BY}'"
            ")"
        )
    )
    session.execute(
        text(
            "SELECT add_compression_policy("
            " CAST(:table AS regclass),"
            " compress_after => CAST(:interval AS interval),"
            " if_not_exists => true"
            ")"
        ),
        dict(table=TABLE, interval=compress_after),
    )


def compress_eligible_chunks(session: Session, compress_after: str) -> int:
    """Compress the chunks the policy would compress, right away rather than when its job next runs.

    :returns: the number of chunks compressed.
    """
    return len(
        session.execute(
            text(
                "SELECT compress_chunk(c, if_not_compressed => true)"
                " FROM show_chunks(CAST(:table AS regclass), older_than => CAST(:interval AS interval)) c"
            ),
            dict(table=TABLE, interval=compress_after),
        ).all()
    )


def table_size(session: Session) -> dict[str, int]:
    """Return the on-disk size of timed_belief in bytes, split into heap (including TOAST) and indexes.

    For a hypertable this sums over its chunks, including compressed ones.
    """
    if is_hypertable(session):
        row = session.execute(
            text(
                "SELECT coalesce(table_bytes, 0) + coalesce(toast_bytes, 0), coalesce(index_bytes, 0)"
                " FROM hypertable_detailed_size(CAST(:table AS regclass))"
            ),
            dict(table=TABLE),
        ).one()
    else:
        row = session.execute(
            text(
                "SELECT pg_table_size(CAST(:table AS regclass)), pg_indexes_size(CAST(:table AS regclass))"
            ),
            dict(table=TABLE),
        ).one()
    return dict(table=row[0], indexes=row[1])
