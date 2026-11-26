"""Optional TimescaleDB support for the timed_belief table.

FlexMeasures runs on plain PostgreSQL, and nothing here is needed for it to work.
Hosts whose PostgreSQL server ships TimescaleDB can convert timed_belief into a hypertable,
partitioned into time chunks on event_start,
of which the ones older than a given age are compressed.
Queries do not change: a hypertable is still a table to SQLAlchemy and to timely-beliefs.

This is deliberately an explicit operation (see ``flexmeasures db-ops enable-timescaledb``),
not a migration.
TimescaleDB's own Docker images install the extension into every new database,
so the extension being present says nothing about whether a host chose this.
And converting a populated table moves every row into chunks under a lock that blocks writes,
which no host should get as a side effect of a routine ``flexmeasures db upgrade``.
The way back (``flexmeasures db-ops disable-timescaledb``) copies the beliefs into a new plain table.

Queries and TimescaleDB's functions are expressed with SQLAlchemy.
The statements SQLAlchemy has no construct for (installing the extension, ANALYZE and the compression settings),
are DDL elements bound to the timed_belief table, so that its name is quoted by SQLAlchemy rather than by hand.
"""

from __future__ import annotations

from sqlalchemy import (
    DDL,
    cast,
    column,
    func,
    insert,
    literal,
    select,
    table,
)
from sqlalchemy.dialects.postgresql import INTERVAL, REGCLASS
from sqlalchemy.orm import Session
from sqlalchemy.schema import AddConstraint, CreateSchema, CreateTable, DropSchema
from sqlalchemy.sql.elements import Cast

from flexmeasures.data.models.time_series import (
    TimedBelief,
    create_sensor_data_source_trigger,
)

TIMED_BELIEF = TimedBelief.__table__
TABLE = TIMED_BELIEF.name
PARTITION_COLUMN = TIMED_BELIEF.c.event_start

#: The sensor_data_source trigger on timed_belief reads the inserted rows from a transition table (REFERENCING NEW TABLE),
#: which hypertables only accept from TimescaleDB 2.18 on.
MINIMUM_VERSION = (2, 18)

#: Chunks this long keep the number of chunks low (a query without a time range is planned against all of them),
#: while the most recent chunk, with its indexes, still fits in memory on most hosts.
DEFAULT_CHUNK_TIME_INTERVAL = "30 days"
#: Beliefs about events older than this are rarely rewritten on a live host, so they can be compressed.
DEFAULT_COMPRESS_AFTER = "30 days"

#: Compressed chunks are stored per segment, and nearly every query asks for one sensor (and often one source),
#: so segmenting by those lets a query decompress only the segments it needs.
COMPRESS_SEGMENT_BY = (TIMED_BELIEF.c.sensor_id, TIMED_BELIEF.c.source_id)
#: The rest of the primary key orders the rows within a segment,
#: so that time-range filters can skip compressed batches, and so that upserts find their conflicts cheaply.
COMPRESS_ORDER_BY = (
    TIMED_BELIEF.c.event_start,
    TIMED_BELIEF.c.belief_horizon,
    TIMED_BELIEF.c.cumulative_probability,
)

#: Where disable-timescaledb parks the hypertable while it copies the beliefs out of it.
#: Moving it there frees the names of timed_belief's indexes for the new plain table.
OLD_HYPERTABLE_SCHEMA = "flexmeasures_timescaledb_old"

# The catalog views we read, declared with just the columns we use.
pg_extension = table(
    "pg_extension", column("extname"), column("extversion"), schema="pg_catalog"
)
pg_available_extensions = table(
    "pg_available_extensions",
    column("name"),
    column("default_version"),
    schema="pg_catalog",
)
hypertables = table(
    "hypertables",
    column("hypertable_schema"),
    column("hypertable_name"),
    schema="timescaledb_information",
)
chunks = table(
    "chunks",
    column("chunk_schema"),
    column("chunk_name"),
    column("is_compressed"),
    schema="timescaledb_information",
)


class TimescaleDBUnavailable(Exception):
    """The database server cannot run TimescaleDB, or runs a version or edition that cannot do what was asked."""


def _timed_belief_regclass() -> Cast:
    """Refer to timed_belief as TimescaleDB's functions expect it, resolved through the search path like any unqualified table name."""
    return cast(literal(TABLE), REGCLASS)


def _interval(value: str) -> Cast:
    """Pass a PostgreSQL interval given as text, such as '7 days', as a bound parameter."""
    return cast(literal(value), INTERVAL)


def _qualified_regclass(schema_column, name_column) -> Cast:
    """Turn the schema and name columns of a TimescaleDB catalog view into a regclass, to compare with one."""
    return cast(func.format("%I.%I", schema_column, name_column), REGCLASS)


def installed_version(session: Session) -> str | None:
    """Return the TimescaleDB version installed in this database, or None if it is not installed."""
    return session.execute(
        select(pg_extension.c.extversion).where(pg_extension.c.extname == "timescaledb")
    ).scalar_one_or_none()


def available_version(session: Session) -> str | None:
    """Return the TimescaleDB version the server could install, or None if it has none."""
    return session.execute(
        select(pg_available_extensions.c.default_version).where(
            pg_available_extensions.c.name == "timescaledb"
        )
    ).scalar_one_or_none()


def setting(session: Session, name: str) -> str | None:
    """Return a server setting, such as 'timescaledb.license', or None if the server does not know it."""
    return session.execute(
        select(func.current_setting(name, True))  # missing_ok
    ).scalar_one()


def supports_compression(session: Session) -> bool:
    """Whether this server runs a TimescaleDB edition that can compress.

    The Apache-licensed edition, offered by some managed services, cannot.
    """
    return setting(session, "timescaledb.license") != "apache"


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
        session.execute(DDL("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        version = installed_version(session)
    if _parse_version(version) < MINIMUM_VERSION:
        raise TimescaleDBUnavailable(
            f"TimescaleDB {version} is installed, but at least {'.'.join(map(str, MINIMUM_VERSION))} is needed,"
            f" because {TABLE} has a trigger that reads the inserted rows from a transition table,"
            " which older versions do not support on hypertables."
        )
    return version


def is_hypertable(session: Session) -> bool:
    """Whether timed_belief (as resolved via the search path) is already a hypertable."""
    if installed_version(session) is None:
        return False
    return (
        session.execute(
            select(func.count())
            .select_from(hypertables)
            .where(
                _qualified_regclass(
                    hypertables.c.hypertable_schema, hypertables.c.hypertable_name
                )
                == _timed_belief_regclass()
            )
        ).scalar_one()
        > 0
    )


def convert_to_hypertable(session: Session, chunk_time_interval: str) -> None:
    """Convert timed_belief into a hypertable, moving any existing rows into chunks.

    The primary key already contains event_start, which TimescaleDB requires of every unique index.
    TimescaleDB's default index on the partition column is not created:
    the existing indexes cover it,
    and an index that the data model does not declare would make ``flexmeasures db migrate`` propose dropping it.

    :param chunk_time_interval: how much event time each chunk spans, as a PostgreSQL interval (e.g. '30 days').
    """
    # SQLAlchemy cannot pass PostgreSQL's named arguments (name => value),
    # so the flags go by position, in the order of create_hypertable's signature.
    session.execute(
        select(
            func.create_hypertable(
                _timed_belief_regclass(),
                func.by_range(PARTITION_COLUMN.name, _interval(chunk_time_interval)),
                False,  # create_default_indexes
                False,  # if_not_exists
                True,  # migrate_data
            )
        )
    )
    # The rows now live in fresh chunk tables, which have no planner statistics yet.
    session.execute(DDL("ANALYZE %(fullname)s").against(TIMED_BELIEF))


def set_chunk_time_interval(session: Session, chunk_time_interval: str) -> None:
    """Make chunks created from now on span this much event time; existing chunks keep theirs."""
    session.execute(
        select(
            func.set_chunk_time_interval(
                _timed_belief_regclass(), _interval(chunk_time_interval)
            )
        )
    )


def enable_compression(session: Session, compress_after: str) -> None:
    """Compress chunks whose events are all older than ``compress_after``, from now on.

    TimescaleDB runs the policy as a background job.
    A policy set earlier is replaced, so that running this again changes the age.
    Compressed chunks still accept inserts, updates, upserts and deletes,
    but these are slower than on uncompressed chunks,
    so pick an age beyond which data is rarely rewritten.

    :param compress_after: a PostgreSQL interval (e.g. '30 days').
    """
    segment_by = ", ".join(c.name for c in COMPRESS_SEGMENT_BY)
    order_by = ", ".join(c.name for c in COMPRESS_ORDER_BY)
    session.execute(
        DDL(
            "ALTER TABLE %(fullname)s SET ("
            " timescaledb.compress,"
            f" timescaledb.compress_segmentby = '{segment_by}',"
            f" timescaledb.compress_orderby = '{order_by}'"
            ")"
        ).against(TIMED_BELIEF)
    )
    session.execute(
        select(
            func.remove_compression_policy(_timed_belief_regclass(), True)  # if_exists
        )
    )
    session.execute(
        select(
            func.add_compression_policy(
                _timed_belief_regclass(), _interval(compress_after)
            )
        )
    )


def compression_policy_age(session: Session) -> str | None:
    """Return the age after which the compression policy compresses chunks, e.g. '30 days', or None if there is no policy."""
    jobs = table(
        "jobs",
        column("hypertable_schema"),
        column("hypertable_name"),
        column("proc_name"),
        column("config"),
        schema="timescaledb_information",
    )
    return session.execute(
        select(jobs.c.config.op("->>")("compress_after")).where(
            jobs.c.proc_name == "policy_compression",
            _qualified_regclass(jobs.c.hypertable_schema, jobs.c.hypertable_name)
            == _timed_belief_regclass(),
        )
    ).scalar_one_or_none()


def compress_eligible_chunks(session: Session, compress_after: str) -> int:
    """Compress the chunks the policy would compress, right away rather than when its job next runs.

    Chunks that were compressed already are left out,
    including ones that took new beliefs since, which the policy recompresses on its own schedule.

    :returns: the number of chunks compressed.
    """
    chunk = func.show_chunks(
        _timed_belief_regclass(), _interval(compress_after)  # older_than
    ).column_valued("chunk")
    uncompressed = select(
        _qualified_regclass(chunks.c.chunk_schema, chunks.c.chunk_name)
    ).where(chunks.c.is_compressed.is_(False))
    return len(
        session.execute(
            select(func.compress_chunk(chunk)).where(chunk.in_(uncompressed))
        ).all()
    )


def count_chunks(session: Session) -> int:
    """Return how many chunks the timed_belief hypertable has."""
    chunk = func.show_chunks(_timed_belief_regclass()).column_valued("chunk")
    return session.execute(
        select(func.count()).select_from(select(chunk).subquery())
    ).scalar_one()


def table_size(session: Session) -> dict[str, int]:
    """Return the on-disk size of timed_belief in bytes, split into heap (including TOAST) and indexes.

    For a hypertable this sums over its chunks, including compressed ones.
    """
    if is_hypertable(session):
        sizes = func.hypertable_detailed_size(_timed_belief_regclass()).table_valued(
            "table_bytes", "index_bytes", "toast_bytes", "total_bytes"
        )
        row = session.execute(
            select(
                func.coalesce(sizes.c.table_bytes, 0)
                + func.coalesce(sizes.c.toast_bytes, 0),
                func.coalesce(sizes.c.index_bytes, 0),
            )
        ).one()
    else:
        row = session.execute(
            select(
                func.pg_table_size(_timed_belief_regclass()),
                func.pg_indexes_size(_timed_belief_regclass()),
            )
        ).one()
    return dict(table=row[0], indexes=row[1])


def decompressed_size(session: Session) -> int:
    """Estimate how many bytes the hypertable's beliefs, with their indexes, would take once decompressed.

    That is about what a plain copy of timed_belief needs.
    Compressed chunks count with the size they had before compression.
    """
    size = table_size(session)
    stats = func.hypertable_compression_stats(_timed_belief_regclass()).table_valued(
        "before_compression_total_bytes", "after_compression_total_bytes"
    )
    before, after = session.execute(
        select(
            func.coalesce(stats.c.before_compression_total_bytes, 0),
            func.coalesce(stats.c.after_compression_total_bytes, 0),
        )
    ).one()
    return size["table"] + size["indexes"] - after + before


def convert_to_plain_table(session: Session) -> int:
    """Replace the timed_belief hypertable with a plain table holding the same beliefs.

    The hypertable is moved into a schema of its own,
    a plain timed_belief is created from the data model in its place (with the same primary key, indexes, foreign keys and trigger),
    the beliefs are copied over (decompressing on the way),
    and the hypertable is dropped, with its chunks and compression policy.
    The indexes and foreign keys are added after the copy, as building them in one go is faster than maintaining them row by row.
    The trigger is installed last, as sensor_data_source already lists every sensor and source that has beliefs.
    It all happens in the session's transaction, which holds an exclusive lock on timed_belief from the start,
    so reads and writes wait until it is committed or rolled back.

    The new table is owned by the role that runs this,
    so privileges granted on the hypertable to other roles must be granted again.

    :returns: the number of beliefs copied.
    """
    connection = session.connection()
    old_schema = session.execute(
        select(hypertables.c.hypertable_schema).where(
            _qualified_regclass(
                hypertables.c.hypertable_schema, hypertables.c.hypertable_name
            )
            == _timed_belief_regclass()
        )
    ).scalar_one()
    if old_schema != session.execute(select(func.current_schema())).scalar_one():
        # The plain table is created through the search path, so it would land in another schema than the hypertable's.
        raise TimescaleDBUnavailable(
            f"{TABLE} is in schema {old_schema}, which is not the first schema in the search path."
        )
    session.execute(CreateSchema(OLD_HYPERTABLE_SCHEMA))
    session.execute(
        DDL(
            f"ALTER TABLE %(fullname)s SET SCHEMA {connection.dialect.identifier_preparer.quote_schema(OLD_HYPERTABLE_SCHEMA)}"
        ).against(TIMED_BELIEF)
    )
    old_timed_belief = table(
        TABLE,
        *[column(c.name) for c in TIMED_BELIEF.columns],
        schema=OLD_HYPERTABLE_SCHEMA,
    )

    session.execute(CreateTable(TIMED_BELIEF, include_foreign_key_constraints=[]))
    # SQLAlchemy only keeps the row count of an INSERT when asked to.
    n_copied = session.execute(
        insert(TIMED_BELIEF)
        .from_select(
            [c.name for c in TIMED_BELIEF.columns],
            select(*[old_timed_belief.c[c.name] for c in TIMED_BELIEF.columns]),
        )
        .execution_options(preserve_rowcount=True)
    ).rowcount
    for index in TIMED_BELIEF.indexes:
        index.create(bind=connection)
    for foreign_key in TIMED_BELIEF.foreign_key_constraints:
        session.execute(AddConstraint(foreign_key))
    create_sensor_data_source_trigger(TIMED_BELIEF, connection)
    session.execute(DropSchema(OLD_HYPERTABLE_SCHEMA, cascade=True))
    session.execute(DDL("ANALYZE %(fullname)s").against(TIMED_BELIEF))
    return n_copied
