"""Refuse duplicate data sources, after merging any that exist.

The unique constraint on data_source treated NULL values as distinct,
so it never refused a second script source (which has no user or account) with the same name, model, version and attributes.
Concurrent calls to get_or_create_source could thus each insert the same source (#2611).
This migration merges each group of such duplicates into its oldest source,
and recreates the constraint with NULLS NOT DISTINCT, which requires PostgreSQL 15 or newer.
The constraint now also includes the source type, which every lookup of a source already filters on,
so that sources differing only in type are not merged.

Revision ID: 7c4e1a9d2b58
Revises: b63a02d5e184
"""

from alembic import op
import sqlalchemy as sa

revision = "7c4e1a9d2b58"
down_revision = "b63a02d5e184"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "data_source_name_key"
IDENTITY_COLUMNS = (
    "name",
    "type",
    "user_id",
    "account_id",
    "model",
    "version",
    "attributes_hash",
)
PREVIOUS_IDENTITY_COLUMNS = (
    "name",
    "user_id",
    "account_id",
    "model",
    "version",
    "attributes_hash",
)

# References that moving to the oldest source can make collide with that source's own rows, so they get merged rather than just moved.
MERGED_REFERENCES = {
    ("timed_belief", "source_id"),
    ("sensor_data_source", "source_id"),
    ("annotation", "source_id"),
}

# The tables linking an annotation to what it annotates, and the column naming what it annotates.
ANNOTATION_LINK_TABLES = {
    "annotations_accounts": "account_id",
    "annotations_assets": "generic_asset_id",
    "annotations_sensors": "sensor_id",
}


def upgrade():
    bind = op.get_bind()
    if bind.dialect.server_version_info < (15,):
        raise RuntimeError(
            "FlexMeasures requires PostgreSQL 15 or newer, as it relies on NULLS NOT DISTINCT to refuse duplicate data sources. "
            f"This database runs PostgreSQL {'.'.join(str(part) for part in bind.dialect.server_version_info)}."
        )
    merge_duplicate_sources(bind)
    op.drop_constraint(CONSTRAINT_NAME, "data_source", type_="unique")
    op.execute(
        f"ALTER TABLE data_source ADD CONSTRAINT {CONSTRAINT_NAME} UNIQUE NULLS NOT DISTINCT ({', '.join(IDENTITY_COLUMNS)})"
    )


def downgrade():
    # Sources merged by the upgrade stay merged.
    op.drop_constraint(CONSTRAINT_NAME, "data_source", type_="unique")
    op.create_unique_constraint(
        CONSTRAINT_NAME, "data_source", list(PREVIOUS_IDENTITY_COLUMNS)
    )


def merge_duplicate_sources(bind):
    """Merge each group of identical data sources into the oldest one, moving over whatever references the newer ones."""
    duplicates = bind.execute(sa.text(f"""
            SELECT keep, duplicate FROM (
                SELECT id AS duplicate, min(id) OVER (PARTITION BY {', '.join(IDENTITY_COLUMNS)}) AS keep
                FROM data_source
            ) AS grouped
            WHERE duplicate <> keep
            ORDER BY keep, duplicate
            """)).all()
    if not duplicates:
        return

    # Plugins may add their own references to data sources; those are moved as they are.
    references = bind.execute(sa.text("""
        SELECT c.conrelid::regclass::text, a.attname
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        WHERE c.contype = 'f' AND c.confrelid = 'data_source'::regclass AND cardinality(c.conkey) = 1
        """)).all()
    other_references = [
        (table, column)
        for table, column in references
        if (table, column) not in MERGED_REFERENCES
    ]

    for keep, duplicate in duplicates:
        ids = dict(keep=keep, duplicate=duplicate)
        moved, dropped = merge_beliefs(bind, **ids)
        merge_annotations(bind, **ids)
        bind.execute(
            sa.text("""
                INSERT INTO sensor_data_source (sensor_id, source_id)
                SELECT sensor_id, :keep FROM sensor_data_source WHERE source_id = :duplicate
                ON CONFLICT DO NOTHING
                """),
            ids,
        )
        for table, column in other_references:
            bind.execute(
                sa.text(
                    f'UPDATE {table} SET "{column}" = :keep WHERE "{column}" = :duplicate'
                ),
                ids,
            )
        # Its remaining sensor_data_source rows cascade.
        bind.execute(sa.text("DELETE FROM data_source WHERE id = :duplicate"), ids)
        print(
            f"Merged data source {duplicate} into identical data source {keep}: "
            f"moved {moved} beliefs, and dropped {dropped} beliefs that data source {keep} already held."
        )


def merge_beliefs(bind, keep: int, duplicate: int) -> tuple[int, int]:
    """Move the beliefs of the duplicate source to the kept one, dropping those the kept source already holds.

    The sensor_data_source summary names the sensors the duplicate has beliefs on,
    so that both statements search timed_belief by its primary key, rather than scanning it whole.
    """
    ids = dict(keep=keep, duplicate=duplicate)
    sensor_ids = (
        bind.execute(
            sa.text(
                "SELECT sensor_id FROM sensor_data_source WHERE source_id = :duplicate"
            ),
            ids,
        )
        .scalars()
        .all()
    )
    if not sensor_ids:
        return 0, 0
    ids["sensor_ids"] = sensor_ids
    dropped = bind.execute(
        sa.text("""
            DELETE FROM timed_belief d
            USING timed_belief k
            WHERE d.source_id = :duplicate AND d.sensor_id = ANY(:sensor_ids)
              AND k.source_id = :keep AND k.sensor_id = d.sensor_id
              AND k.event_start = d.event_start AND k.belief_horizon = d.belief_horizon
              AND k.cumulative_probability = d.cumulative_probability
            """),
        ids,
    ).rowcount
    moved = bind.execute(
        sa.text("""
            UPDATE timed_belief SET source_id = :keep
            WHERE source_id = :duplicate AND sensor_id = ANY(:sensor_ids)
            """),
        ids,
    ).rowcount
    return moved, dropped


def merge_annotations(bind, keep: int, duplicate: int):
    """Move the annotations of the duplicate source to the kept one.

    An annotation the kept source already made (same content, start, belief time and type) is not moved, but merged:
    the kept annotation takes over what it annotates, and the duplicate annotation is deleted.
    """
    ids = dict(keep=keep, duplicate=duplicate)
    same_annotations = """
        SELECT d.id AS duplicate_annotation, k.id AS kept_annotation
        FROM annotation d
        JOIN annotation k
          ON k.source_id = :keep AND k.content = d.content AND k.start = d.start
         AND k.belief_time = d.belief_time AND k.type = d.type
        WHERE d.source_id = :duplicate
    """
    for link_table, annotated_column in ANNOTATION_LINK_TABLES.items():
        bind.execute(
            sa.text(f"""
                INSERT INTO {link_table} ({annotated_column}, annotation_id)
                SELECT l.{annotated_column}, same.kept_annotation
                FROM {link_table} l
                JOIN ({same_annotations}) AS same ON l.annotation_id = same.duplicate_annotation
                ON CONFLICT DO NOTHING
                """),
            ids,
        )
    # Their links cascade.
    bind.execute(
        sa.text(
            f"DELETE FROM annotation WHERE id IN (SELECT duplicate_annotation FROM ({same_annotations}) AS same)"
        ),
        ids,
    )
    bind.execute(
        sa.text("UPDATE annotation SET source_id = :keep WHERE source_id = :duplicate"),
        ids,
    )
