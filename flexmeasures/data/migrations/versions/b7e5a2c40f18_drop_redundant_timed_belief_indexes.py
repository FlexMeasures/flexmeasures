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

Revision ID: b7e5a2c40f18
Revises: d4a7c1e93b52
Create Date: 2026-08-03

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "b7e5a2c40f18"
down_revision = "d4a7c1e93b52"
branch_labels = None
depends_on = None

REDUNDANT_COLUMNS = ("event_start", "sensor_id")

# Only plain, single-column, non-unique indexes on the given column qualify.
# Excluding unique and constraint-backing indexes keeps the primary key well out of reach,
# along with any unique constraint a deployment may have added.
# The namespace is pinned to current_schema(),
# so a same-named table in another schema is never touched.
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
   AND n.nspname = current_schema()
   AND x.indnatts = 1
   AND NOT x.indisunique
   AND NOT x.indisprimary
   AND a.attname = ANY(:columns)
   AND NOT EXISTS (
       SELECT 1 FROM pg_constraint c WHERE c.conindid = x.indexrelid
   )
"""


def upgrade():
    names = (
        op.get_bind()
        .execute(sa.text(FIND_REDUNDANT_INDEXES), {"columns": list(REDUNDANT_COLUMNS)})
        .scalars()
        .all()
    )
    for qualified_name in names:
        # The query returns identifiers already quoted by PostgreSQL's own quote_ident(),
        # so names needing quoting (or containing quotes) are handled correctly.
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {qualified_name}")


def downgrade():
    # Recreate under the naming convention this project's metadata uses.
    for column in REDUNDANT_COLUMNS:
        with op.get_context().autocommit_block():
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS timed_belief_{column}_idx"
                f" ON timed_belief ({column})"
            )
