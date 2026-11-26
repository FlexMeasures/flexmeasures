"""Helpers for database migrations that change indexes on a table FlexMeasures keeps writing to, such as timed_belief.

On a plain table, such migrations build and drop indexes ``CONCURRENTLY``, so that writes can go on meanwhile.
TimescaleDB refuses that on a hypertable (see ``flexmeasures db-ops enable-timescaledb``),
as each chunk has its own copy of every index.
These helpers leave out ``CONCURRENTLY`` on a hypertable,
and build a new index one chunk at a time instead (``timescaledb.transaction_per_chunk``),
so that a migration works on both, and blocks writes to a hypertable only one chunk at a time.

Call them inside ``op.get_context().autocommit_block()``, as neither way of building an index may run inside a transaction.
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
from sqlalchemy import column, func, select, table

pg_extension = table("pg_extension", column("extname"), schema="pg_catalog")
hypertables = table(
    "hypertables",
    column("hypertable_schema"),
    column("hypertable_name"),
    schema="timescaledb_information",
)


def is_hypertable(schema: str, table_name: str) -> bool:
    """Whether the given table (with its schema unquoted) is a TimescaleDB hypertable."""
    bind = op.get_bind()
    # Without the extension, TimescaleDB's catalog views do not exist to be queried.
    if (
        bind.execute(
            select(pg_extension.c.extname).where(
                pg_extension.c.extname == "timescaledb"
            )
        ).first()
        is None
    ):
        return False
    return (
        bind.execute(
            select(func.count())
            .select_from(hypertables)
            .where(
                hypertables.c.hypertable_schema == schema,
                hypertables.c.hypertable_name == table_name,
            )
        ).scalar_one()
        > 0
    )


def create_index_online(
    name: str,
    schema: str,
    table_name: str,
    columns: Sequence[str],
    if_not_exists: bool = False,
) -> None:
    """Create a (non-unique) index, letting writes to the table go on meanwhile, or on a hypertable, all but those to one chunk at a time.

    TimescaleDB builds unique indexes on a hypertable neither concurrently nor per chunk,
    so a migration that needs one there has to build it in a transaction, blocking writes until it is done.

    :param name:        the index name, unquoted; the index is created in the schema of its table.
    :param schema:      the table's schema, unquoted.
    :param table_name:  the table name, unquoted.
    :param columns:     the indexed column names, unquoted.
    """
    preparer = op.get_bind().dialect.identifier_preparer
    statement = (
        f"{'IF NOT EXISTS ' if if_not_exists else ''}{preparer.quote(name)}"
        f" ON {preparer.quote_schema(schema)}.{preparer.quote(table_name)}"
        f" ({', '.join(preparer.quote(c) for c in columns)})"
    )
    if is_hypertable(schema, table_name):
        op.execute(f"CREATE INDEX {statement} WITH (timescaledb.transaction_per_chunk)")
    else:
        op.execute(f"CREATE INDEX CONCURRENTLY {statement}")


def drop_index_online(qualified_name: str, schema: str, table_name: str) -> None:
    """Drop an index if it exists, letting writes to the table go on meanwhile, except on a hypertable.

    Dropping an index from a hypertable cannot be done concurrently,
    but takes only as long as removing the files of each chunk's copy of it.

    :param qualified_name:  the index's schema-qualified name, quoted as SQL needs it.
    :param schema:          the schema of the index's table, unquoted.
    :param table_name:      the name of the index's table, unquoted.
    """
    if is_hypertable(schema, table_name):
        op.execute(f"DROP INDEX IF EXISTS {qualified_name}")
    else:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {qualified_name}")
