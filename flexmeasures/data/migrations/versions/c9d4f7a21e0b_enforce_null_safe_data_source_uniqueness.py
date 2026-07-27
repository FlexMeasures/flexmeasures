"""Enforce NULL-safe uniqueness of data sources

The data_source table had a unique constraint over
(name, user_id, account_id, model, version, attributes_hash), but most of
these columns are nullable and PostgreSQL treats NULLs as distinct values,
so the constraint never fired for rows with NULLs in any of these columns.
Notably, scheduler and forecaster sources have no user or account, so
concurrent get-or-create calls (e.g. several workers computing their first
schedules against a fresh database) could insert duplicate rows. Every
subsequent lookup then failed with MultipleResultsFound, wedging all
scheduling jobs.

This migration:

1. Deduplicates existing data_source rows that are identical in all key
   columns (treating NULLs as equal). The row with the lowest id is kept,
   and timed_belief and annotation rows are repointed to it. In the corner
   case where both a kept and a duplicate source recorded a belief with the
   same primary key coordinates (sensor, event start, belief horizon,
   cumulative probability), the kept source's belief wins and the duplicate
   source's belief is dropped (they are duplicate recordings by the same
   logical source).
2. Replaces the NULL-blind unique constraint with a unique expression index
   that coalesces NULLs to sentinel values which cannot occur in real data
   (negative ids, empty strings, an empty bytes hash).

Revision ID: c9d4f7a21e0b
Revises: 4b0f2e9c1a6d
Create Date: 2026-07-27 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "c9d4f7a21e0b"
down_revision = "4b0f2e9c1a6d"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # Legacy tables (pre-timed_belief data model) that may still exist on
    # long-lived databases and reference data_source; they share the same
    # primary key layout: (datetime, sensor_id, horizon, data_source_id).
    legacy_tables = [
        table
        for table in ("power", "price", "weather")
        if sa.inspect(bind).has_table(table)
    ]

    # 1. Deduplicate: find groups of rows that are identical in all key columns.
    #    GROUP BY conveniently treats NULLs as equal, matching the semantics of
    #    the NULL-safe unique index we are about to create.
    duplicate_groups = bind.execute(
        text(
            "SELECT min(id) AS keep_id, array_agg(id ORDER BY id) AS ids "
            "FROM data_source "
            "GROUP BY name, user_id, account_id, model, version, attributes_hash "
            "HAVING count(*) > 1"
        )
    ).fetchall()
    for keep_id, ids in duplicate_groups:
        for dupe_id in ids:
            if dupe_id == keep_id:
                continue
            # Repoint beliefs to the kept source, except where the kept source
            # already recorded a belief with the same primary key coordinates.
            bind.execute(
                text(
                    "UPDATE timed_belief tb SET source_id = :keep_id "
                    "WHERE tb.source_id = :dupe_id "
                    "AND NOT EXISTS ("
                    "    SELECT 1 FROM timed_belief tb2 "
                    "    WHERE tb2.source_id = :keep_id "
                    "    AND tb2.sensor_id = tb.sensor_id "
                    "    AND tb2.event_start = tb.event_start "
                    "    AND tb2.belief_horizon = tb.belief_horizon "
                    "    AND tb2.cumulative_probability = tb.cumulative_probability"
                    ")"
                ),
                {"keep_id": keep_id, "dupe_id": dupe_id},
            )
            # Any beliefs still pointing to the duplicate source collide with
            # beliefs of the kept source: drop them in favour of the latter.
            bind.execute(
                text("DELETE FROM timed_belief WHERE source_id = :dupe_id"),
                {"dupe_id": dupe_id},
            )
            bind.execute(
                text(
                    "UPDATE annotation SET source_id = :keep_id WHERE source_id = :dupe_id"
                ),
                {"keep_id": keep_id, "dupe_id": dupe_id},
            )
            # Do the same for legacy tables that may still reference data_source.
            for table in legacy_tables:
                bind.execute(
                    text(
                        f"UPDATE {table} t SET data_source_id = :keep_id "  # nosec B608
                        f"WHERE t.data_source_id = :dupe_id "
                        f"AND NOT EXISTS ("
                        f"    SELECT 1 FROM {table} t2 "
                        f"    WHERE t2.data_source_id = :keep_id "
                        f"    AND t2.datetime = t.datetime "
                        f"    AND t2.sensor_id = t.sensor_id "
                        f"    AND t2.horizon = t.horizon"
                        f")"
                    ),
                    {"keep_id": keep_id, "dupe_id": dupe_id},
                )
                bind.execute(
                    text(
                        f"DELETE FROM {table} WHERE data_source_id = :dupe_id"
                    ),  # nosec B608
                    {"dupe_id": dupe_id},
                )
            bind.execute(
                text("DELETE FROM data_source WHERE id = :dupe_id"),
                {"dupe_id": dupe_id},
            )

    # 2. Replace the NULL-blind unique constraint with a NULL-safe unique index.
    op.drop_constraint("data_source_name_key", "data_source", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX data_source_nullsafe_uniqueness_idx ON data_source "
        "(name, coalesce(user_id, -1), coalesce(account_id, -1), "
        "coalesce(model, ''), coalesce(version, ''), "
        "coalesce(attributes_hash, '\\x'::bytea))"
    )


def downgrade():
    """Restore the previous (NULL-blind) unique constraint.

    The deduplication of step 1 of the upgrade is intentionally not reversed:
    the removed rows were duplicates, and the previous get-or-create logic
    works fine (better, even) without them.
    """
    op.drop_index("data_source_nullsafe_uniqueness_idx", table_name="data_source")
    op.create_unique_constraint(
        "data_source_name_key",
        "data_source",
        ["name", "user_id", "account_id", "model", "version", "attributes_hash"],
    )
