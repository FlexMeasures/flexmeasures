"""reorder the timed_belief primary key

Change the column order of ``timed_belief_pkey`` from whatever order SQLAlchemy happened to collect the columns in,
to a deliberate one:

    (sensor_id, source_id, event_start, belief_horizon, cumulative_probability)

The set of columns is unchanged, so uniqueness semantics are identical:
this is purely a reordering.
``timely_beliefs`` passes ``index_elements`` to ``on_conflict_do_update`` as a set,
so upserts are unaffected.

Why this order:

- ``sensor_id`` first, because virtually every query filters on a single sensor.
  A key that does not lead with it cannot serve those queries at all.
- ``source_id`` second, so that ``(sensor_id, source_id, event_start, belief_horizon)`` is a *prefix* of the key.
  Deployments carrying a separate composite index on exactly those columns no longer need it,
  and this migration drops it (see below), typically the single largest win here.
- ``cumulative_probability`` last,
  because it is very nearly a constant (0.5 for every deterministic belief),
  and contributes no selectivity wherever it sits.
- ``sensor_id`` and ``source_id`` adjacent:
  both are 4-byte integers,
  so keeping them together avoids the alignment padding that separating them forces into every index tuple.
  Measured at roughly 15% of the index's size.

Note that this rebuilds an index but does **not** rewrite the table:
no heap pages are touched, and no other index is affected.

The swap is done online, so this does not need a maintenance window.
Building the replacement index is the slow part, and it runs ``CONCURRENTLY`` inside an
``autocommit_block``, so reads and writes continue throughout.
Only the swap itself takes an ACCESS EXCLUSIVE lock,
and that is catalog-only (milliseconds) because the index already exists by then.
The redundant composite index is dropped ``CONCURRENTLY`` too.

The trade for staying online is that the concurrent steps are not transactional:
if the migration fails partway, an unused ``timed_belief_pkey_new`` index may be left behind.
Re-running the migration cleans it up first, so a retry is safe.
A failed ``CREATE INDEX CONCURRENTLY`` can also leave an *invalid* index,
which the same cleanup removes.

Revision ID: d4a7c1e93b52
Revises: 3bc1e29ca1f4
Create Date: 2026-08-03

"""

import sqlalchemy as sa
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

# Some deployments carry a hand-added composite index on exactly the first four columns of NEW_ORDER,
# which the reordered primary key makes redundant.
# Drop it only if it is present *and* matches that definition,
# so we never drop an index that happens to share the name but covers something else.
REDUNDANT_INDEX = "idx_tb_sensor_source_event_horizon"
# The check is a plain query rather than a DO block,
# because DROP INDEX CONCURRENTLY cannot run inside one.
IS_REDUNDANT_INDEX_PRESENT = """
SELECT 1 FROM pg_indexes
 WHERE schemaname = current_schema()
   AND tablename = 'timed_belief'
   AND indexname = :name
   AND indexdef LIKE '%(sensor_id, source_id, event_start, belief_horizon)%'
"""

RECREATE_REDUNDANT_INDEX = f"""
CREATE INDEX CONCURRENTLY IF NOT EXISTS {REDUNDANT_INDEX}
    ON timed_belief (sensor_id, source_id, event_start, belief_horizon)
"""


TEMP_INDEX = "timed_belief_pkey_new"


def _swap_primary_key(order: list[str]) -> None:
    """Rebuild timed_belief's primary key in the given column order, without a maintenance window.

    The replacement index is built ``CONCURRENTLY`` outside a transaction, so reads and
    writes continue while it is built.
    Promoting it to the primary key then costs only a catalog update.
    """
    # A previous failed run can leave the temporary index behind, possibly marked invalid.
    # Drop it first so a retry is always safe.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {TEMP_INDEX}")
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY {TEMP_INDEX}"
            f" ON timed_belief ({', '.join(order)})"
        )
    op.drop_constraint("timed_belief_pkey", "timed_belief", type_="primary")
    # USING INDEX adopts the index we just built, so no rebuild happens under the lock.
    # PostgreSQL renames it to the constraint name.
    op.execute(
        f"ALTER TABLE timed_belief"
        f" ADD CONSTRAINT timed_belief_pkey PRIMARY KEY USING INDEX {TEMP_INDEX}"
    )


def upgrade():
    _swap_primary_key(NEW_ORDER)
    present = (
        op.get_bind()
        .execute(sa.text(IS_REDUNDANT_INDEX_PRESENT), {"name": REDUNDANT_INDEX})
        .scalar()
    )
    if present:
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {REDUNDANT_INDEX}")


def downgrade():
    # Restore the composite index first,
    # so the queries that relied on it are not left unserved in between.
    with op.get_context().autocommit_block():
        op.execute(RECREATE_REDUNDANT_INDEX)
    _swap_primary_key(OLD_ORDER)
