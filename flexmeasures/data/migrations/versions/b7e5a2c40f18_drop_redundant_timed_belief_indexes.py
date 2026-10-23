"""drop redundant single-column indexes on timed_belief

``timed_belief`` carried single-column indexes on ``event_start`` and on ``sensor_id``,
created because ``timely_beliefs`` declared ``index=True`` on both columns.
Each is fully covered by a composite index the same library declares:

    (event_start) -> timed_belief_search_session_idx
                     (event_start, sensor_id, source_id) INCLUDE (belief_horizon)
    (sensor_id)   -> timed_belief_search_session_singleevent_idx
                     (sensor_id, event_start)

A btree serves a leading-column lookup just as well as a dedicated single-column index,
so neither offered anything a query could use.
They only occupied space on what is usually the largest table,
and slowed down every write that had to maintain them.
In the deployment where this was profiled, neither had ever served a single index scan,
while every other index on the table had scan counts in the hundreds of thousands or millions.

SeitaBV/timely-beliefs#244 (released in 4.2.0) stopped declaring them,
so newly created databases no longer get them.
This migration removes them from existing ones.

Dropping the ``sensor_id`` index is safe for the ON DELETE CASCADE on its foreign key:
PostgreSQL only needs to find rows *by* ``sensor_id``,
and ``timed_belief_search_session_singleevent_idx`` leads with exactly that column.

Rather than dropping by name, this looks for single-column non-unique indexes on those columns,
so it works regardless of the naming convention a deployment's indexes were created under,
and skips anything already absent.

The drops run ``CONCURRENTLY``, so no maintenance window is needed:
reads and writes continue throughout, and no exclusive lock is taken on the table.

Finally, this reports any *other* index it finds that the reordered primary key of ``d4a7c1e93b52`` has made redundant,
without dropping it.
An index whose columns are a prefix of the primary key answers nothing the primary key does not already answer,
but such an index is not part of FlexMeasures' schema:
a deployment that has one added it by hand, and only that deployment knows what it was for.
So the operator is told which ones qualify and left to decide.
Reporting this here rather than in ``d4a7c1e93b52`` keeps the list to indexes FlexMeasures will not touch itself,
since by this point the two above have already been dropped.

Revision ID: b7e5a2c40f18
Revises: d4a7c1e93b52
Create Date: 2026-08-03

"""

import logging

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger("alembic.runtime.migration")


def _report(message: str):
    """Tell the operator which indexes this migration touched on their database.

    Printed as well as logged, because FlexMeasures' logging setup does not surface the alembic logger,
    and the upgrade output is the only record a deployment gets of what was dropped.
    """
    print(message, flush=True)
    logger.info(message)


# revision identifiers, used by Alembic.
revision = "b7e5a2c40f18"
down_revision = "d4a7c1e93b52"
branch_labels = None
depends_on = None

REDUNDANT_COLUMNS = ("event_start", "sensor_id")

# Only used to name the primary key's columns in the message below.
# The query itself reads them from the catalog, so the two cannot drift apart in what they act on.
PRIMARY_KEY_ORDER = (
    "sensor_id",
    "source_id",
    "event_start",
    "belief_horizon",
    "cumulative_probability",
)

# Only plain, single-column, non-unique indexes on the given column qualify.
# Excluding unique and constraint-backing indexes keeps the primary key well out of reach,
# along with any unique constraint a deployment may have added.
# Partial and expression indexes are excluded too:
# a deployment-specific index with a WHERE predicate answers queries the composite indexes do not,
# so it is not redundant even though it covers the same column.
# The namespace is resolved from the catalog rather than assumed to be current_schema(),
# so that the lookup and the DDL cannot disagree about which timed_belief is meant,
# and a same-named table in another schema is never touched.
# Selected as a plain query rather than looped over in a DO block,
# because DROP INDEX CONCURRENTLY cannot run inside one.
FIND_REDUNDANT_INDEXES = """
SELECT quote_ident(n.nspname) || '.' || quote_ident(i.relname)
  FROM pg_index x
  JOIN pg_class i ON i.oid = x.indexrelid
  JOIN pg_class t ON t.oid = x.indrelid
  JOIN pg_namespace n ON n.oid = t.relnamespace
  JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = x.indkey[0]
 WHERE t.relname = 'timed_belief'
   AND n.nspname = :schema
   AND x.indnatts = 1
   AND x.indnkeyatts = 1
   AND NOT x.indisunique
   AND NOT x.indisprimary
   AND x.indpred IS NULL
   AND x.indexprs IS NULL
   AND a.attname = ANY(:columns)
   AND NOT EXISTS (
       SELECT 1 FROM pg_constraint c WHERE c.conindid = x.indexrelid
   )
"""


# Indexes that the reordered primary key of d4a7c1e93b52 has made redundant.
# An index is redundant when its key columns are a prefix of the primary key's,
# because a btree serves a leading-column lookup just as well as a dedicated index on those columns.
# The primary key's own column list is read from the catalog rather than repeated here,
# so this stays correct if that order is ever revised again.
#
# The conditions are deliberately strict, because the point is to suggest a drop to a human:
# anything that might still be pulling weight must not appear.
# So partial and expression indexes are excluded (they answer queries the primary key does not),
# as are unique and constraint-backing indexes, non-btree indexes,
# indexes with INCLUDE columns (indnatts > indnkeyatts), invalid ones,
# and anything with a non-default sort order or operator class,
# since the primary key's plain ascending, default-opclass columns cannot substitute for those.
FIND_PREFIX_REDUNDANT_INDEXES = """
WITH pk AS (
    SELECT x.indrelid AS relid,
           string_to_array(x.indkey::text, ' ')::int[] AS keys,
           x.indnkeyatts AS natts
      FROM pg_index x
      JOIN pg_class t ON t.oid = x.indrelid
      JOIN pg_namespace n ON n.oid = t.relnamespace
     WHERE t.relname = 'timed_belief'
       AND n.nspname = :schema
       AND x.indisprimary
)
SELECT quote_ident(n.nspname) || '.' || quote_ident(i.relname)
  FROM pg_index x
  JOIN pk ON pk.relid = x.indrelid
  JOIN pg_class i ON i.oid = x.indexrelid
  JOIN pg_class t ON t.oid = x.indrelid
  JOIN pg_namespace n ON n.oid = t.relnamespace
  JOIN pg_am am ON am.oid = i.relam
 WHERE am.amname = 'btree'
   AND x.indisvalid
   AND NOT x.indisunique
   AND NOT x.indisprimary
   AND x.indpred IS NULL
   AND x.indexprs IS NULL
   AND x.indnatts = x.indnkeyatts
   AND x.indnkeyatts <= pk.natts
   AND string_to_array(x.indoption::text, ' ')::int[] = array_fill(0, ARRAY[x.indnkeyatts])
   AND (string_to_array(x.indkey::text, ' ')::int[])[1:x.indnkeyatts] = pk.keys[1:x.indnkeyatts]
   AND NOT EXISTS (
       SELECT 1 FROM pg_constraint c WHERE c.conindid = x.indexrelid
   )
   AND NOT EXISTS (
       SELECT 1
         FROM unnest(string_to_array(x.indclass::text, ' ')::oid[]) AS cls(oid)
         JOIN pg_opclass o ON o.oid = cls.oid
        WHERE NOT o.opcdefault
   )
 ORDER BY 1
"""


RESOLVE_SCHEMA = """
SELECT n.nspname, quote_ident(n.nspname)
  FROM pg_class t
  JOIN pg_namespace n ON n.oid = t.relnamespace
 WHERE t.relname = 'timed_belief'
   AND t.relkind = 'r'
   AND pg_table_is_visible(t.oid)
"""


def upgrade():
    raw_schema, _quoted_schema = op.get_bind().execute(sa.text(RESOLVE_SCHEMA)).one()
    names = (
        op.get_bind()
        .execute(
            sa.text(FIND_REDUNDANT_INDEXES),
            {"columns": list(REDUNDANT_COLUMNS), "schema": raw_schema},
        )
        .scalars()
        .all()
    )
    for qualified_name in names:
        # The query returns identifiers already quoted by PostgreSQL's own quote_ident(),
        # so names needing quoting (or containing quotes) are handled correctly.
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {qualified_name}")

    # Which of the two a database carries varies with its age and the timely-beliefs version that built it,
    # so say what was actually dropped here rather than what the migration can drop in general.
    if names:
        _report(
            f"Dropped {len(names)} redundant single-column index(es) on timed_belief: {', '.join(names)}."
            f" Note that a downgrade recreates the indexes on both {' and '.join(REDUNDANT_COLUMNS)},"
            f" so a database that carried only one of them gains the other."
        )
    else:
        _report(
            "No redundant single-column indexes on timed_belief were present, so none were dropped."
        )

    _suggest_dropping_prefix_indexes(raw_schema)


def _suggest_dropping_prefix_indexes(raw_schema: str):
    """Name the indexes the reordered primary key has made redundant, and leave them in place.

    Silent when there are none, which is the case for any database whose schema FlexMeasures created:
    a line saying that nothing was found would only be noise about indexes this project never declared.
    """
    names = (
        op.get_bind()
        .execute(sa.text(FIND_PREFIX_REDUNDANT_INDEXES), {"schema": raw_schema})
        .scalars()
        .all()
    )
    if not names:
        return
    _report(
        f"The reordered primary key on timed_belief has made {len(names)} further index(es) redundant,"
        f" which this migration leaves in place because they are not part of FlexMeasures' schema:"
        f" {', '.join(names)}."
        f" Each covers a prefix of ({', '.join(PRIMARY_KEY_ORDER)}), so the primary key already serves the queries they serve."
        f" To drop one without locking the table: DROP INDEX CONCURRENTLY <name>;"
    )


def downgrade():
    # Recreate under the naming convention this project's metadata uses.
    # The quoted form here, because it is interpolated into raw SQL.
    #
    # Both are recreated unconditionally, unlike the hand-added composite index in d4a7c1e93b52,
    # and the difference is provenance.
    # These two are FlexMeasures' own schema:
    # timely-beliefs declared index=True on both columns before 4.2.0,
    # so a database on the version being downgraded to would have had them.
    # Restoring them is restoring our schema, not inventing schema for the operator.
    # A database that carried only one of them does gain the other, which the message below points out,
    # and dropping it again is a one-liner.
    _raw_schema, schema = op.get_bind().execute(sa.text(RESOLVE_SCHEMA)).one()
    for column in REDUNDANT_COLUMNS:
        with op.get_context().autocommit_block():
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS timed_belief_{column}_idx"
                f" ON {schema}.timed_belief ({column})"
            )
    _report(
        f"Recreated the single-column indexes on timed_belief"
        f" ({', '.join(f'timed_belief_{column}_idx' for column in REDUNDANT_COLUMNS)}),"
        f" which timely-beliefs declared before 4.2.0."
        f" If this database did not carry both of them before it was upgraded,"
        f" it now has one it did not have, and dropping that again is safe."
    )
