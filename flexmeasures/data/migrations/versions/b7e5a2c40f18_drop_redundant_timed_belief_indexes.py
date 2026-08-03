"""drop redundant single-column indexes on timed_belief

``timed_belief`` carried single-column indexes on ``event_start`` and on
``sensor_id``, created because ``timely_beliefs`` declared ``index=True`` on both
columns. Each is fully covered by a composite index the same library declares:

    (event_start) -> timed_belief_search_session_idx
                     (event_start, sensor_id, source_id) INCLUDE (belief_horizon)
    (sensor_id)   -> timed_belief_search_session_singleevent_idx
                     (sensor_id, event_start)

A btree serves a leading-column lookup just as well as a dedicated single-column
index, so neither offered anything a query could use -- they only occupied space
on what is usually the largest table, and slowed down every write that had to
maintain them. In the deployment where this was profiled, neither had ever served
a single index scan, while every other index on the table had scan counts in the
hundreds of thousands or millions.

SeitaBV/timely-beliefs#244 (released in 4.2.0) stopped declaring them, so newly
created databases no longer get them. This migration removes them from existing
ones.

Dropping the ``sensor_id`` index is safe for the ON DELETE CASCADE on its foreign
key: PostgreSQL only needs to find rows *by* ``sensor_id``, and
``timed_belief_search_session_singleevent_idx`` leads with exactly that column.

Rather than dropping by name, this looks for single-column non-unique indexes on
those columns, so it works regardless of the naming convention a deployment's
indexes were created under, and skips anything already absent.

.. note:: These are plain ``DROP INDEX`` statements, which take a brief exclusive
   lock on the table. To avoid even that on a large database, drop them outside
   Alembic with ``DROP INDEX CONCURRENTLY`` before running this migration -- it
   will then find nothing to do and pass straight through.

Revision ID: b7e5a2c40f18
Revises: d4a7c1e93b52
Create Date: 2026-08-03

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "b7e5a2c40f18"
down_revision = "d4a7c1e93b52"
branch_labels = None
depends_on = None

REDUNDANT_COLUMNS = ("event_start", "sensor_id")

# Only plain, single-column, non-unique indexes on the given column qualify.
# Excluding unique and constraint-backing indexes keeps the primary key (and any
# unique constraint a deployment may have added) well out of reach.
DROP_REDUNDANT_INDEXES = """
DO $$
DECLARE
    idx text;
BEGIN
    FOR idx IN
        SELECT i.relname
          FROM pg_index x
          JOIN pg_class i ON i.oid = x.indexrelid
          JOIN pg_class t ON t.oid = x.indrelid
          JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = x.indkey[0]
         WHERE t.relname = 'timed_belief'
           AND x.indnatts = 1
           AND NOT x.indisunique
           AND NOT x.indisprimary
           AND a.attname = ANY(ARRAY['event_start', 'sensor_id'])
           AND NOT EXISTS (
               SELECT 1 FROM pg_constraint c WHERE c.conindid = x.indexrelid
           )
    LOOP
        RAISE NOTICE 'dropping redundant index %', idx;
        EXECUTE format('DROP INDEX %I', idx);
    END LOOP;
END $$;
"""


def upgrade():
    op.execute(DROP_REDUNDANT_INDEXES)


def downgrade():
    # Recreate under the naming convention this project's metadata uses.
    for column in REDUNDANT_COLUMNS:
        op.create_index(
            f"timed_belief_{column}_idx",
            "timed_belief",
            [column],
            unique=False,
        )
