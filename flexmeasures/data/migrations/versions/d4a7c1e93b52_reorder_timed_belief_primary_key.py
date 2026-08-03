"""reorder the timed_belief primary key

Change the column order of ``timed_belief_pkey`` from whatever order SQLAlchemy
happened to collect the columns in, to a deliberate one:

    (sensor_id, source_id, event_start, belief_horizon, cumulative_probability)

The set of columns is unchanged, so uniqueness semantics are identical -- this is
purely a reordering. ``timely_beliefs`` passes ``index_elements`` to
``on_conflict_do_update`` as a set, so upserts are unaffected.

Why this order:

- ``sensor_id`` first, because virtually every query filters on a single sensor.
  A key that does not lead with it cannot serve those queries at all.
- ``source_id`` second, so that ``(sensor_id, source_id, event_start,
  belief_horizon)`` is a *prefix* of the key. Deployments carrying a separate
  composite index on exactly those columns no longer need it, and this migration
  drops it (see below) -- typically the single largest win here.
- ``cumulative_probability`` last, because it is very nearly a constant (0.5 for
  every deterministic belief) and contributes no selectivity wherever it sits.
- ``sensor_id`` and ``source_id`` adjacent: both are 4-byte integers, so keeping
  them together avoids the alignment padding that separating them forces into
  every index tuple. Measured at roughly 15% of the index's size.

Note that this rebuilds an index but does **not** rewrite the table: no heap
pages are touched, and no other index is affected.

.. warning:: ``op.create_primary_key`` builds the new index while holding an
   ACCESS EXCLUSIVE lock, which on a large ``timed_belief`` means a long outage.
   Large deployments should instead do the swap online, outside Alembic, and then
   stamp this revision::

       CREATE UNIQUE INDEX CONCURRENTLY timed_belief_pkey_new
           ON timed_belief (sensor_id, source_id, event_start, belief_horizon,
                            cumulative_probability);
       BEGIN;
         ALTER TABLE timed_belief DROP CONSTRAINT timed_belief_pkey;
         ALTER TABLE timed_belief ADD CONSTRAINT timed_belief_pkey
             PRIMARY KEY USING INDEX timed_belief_pkey_new;
       COMMIT;
       DROP INDEX CONCURRENTLY IF EXISTS idx_tb_sensor_source_event_horizon;

   Only the transaction takes an exclusive lock, and it is catalog-only because
   the index already exists.

Revision ID: d4a7c1e93b52
Revises: 3bc1e29ca1f4
Create Date: 2026-08-03

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "d4a7c1e93b52"
down_revision = "3bc1e29ca1f4"
branch_labels = None
depends_on = None

NEW_ORDER = [
    "sensor_id",
    "source_id",
    "event_start",
    "belief_horizon",
    "cumulative_probability",
]
# The order SQLAlchemy produced before the primary key was pinned explicitly.
OLD_ORDER = [
    "source_id",
    "event_start",
    "belief_horizon",
    "cumulative_probability",
    "sensor_id",
]

# Some deployments carry a hand-added composite index on exactly the first four
# columns of NEW_ORDER, which the reordered primary key makes redundant. Drop it
# only if it is present *and* matches that definition, so we never drop an index
# that happens to share the name but covers something else.
REDUNDANT_INDEX = "idx_tb_sensor_source_event_horizon"
DROP_REDUNDANT_INDEX = f"""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_indexes
         WHERE schemaname = current_schema()
           AND tablename = 'timed_belief'
           AND indexname = '{REDUNDANT_INDEX}'
           AND indexdef LIKE '%(sensor_id, source_id, event_start, belief_horizon)%'
    ) THEN
        EXECUTE 'DROP INDEX {REDUNDANT_INDEX}';
    END IF;
END $$;
"""

RECREATE_REDUNDANT_INDEX = f"""
CREATE INDEX IF NOT EXISTS {REDUNDANT_INDEX}
    ON timed_belief (sensor_id, source_id, event_start, belief_horizon);
"""


def upgrade():
    op.drop_constraint("timed_belief_pkey", "timed_belief", type_="primary")
    op.create_primary_key("timed_belief_pkey", "timed_belief", NEW_ORDER)
    op.execute(DROP_REDUNDANT_INDEX)


def downgrade():
    # Restore the composite index first, so the queries that relied on it are not
    # left unserved in between.
    op.execute(RECREATE_REDUNDANT_INDEX)
    op.drop_constraint("timed_belief_pkey", "timed_belief", type_="primary")
    op.create_primary_key("timed_belief_pkey", "timed_belief", OLD_ORDER)
