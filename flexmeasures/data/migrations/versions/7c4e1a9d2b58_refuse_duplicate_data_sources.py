"""Refuse duplicate data sources, after merging any that exist.

The unique constraint on data_source treated NULL values as distinct,
so it never refused a second source without a user or account (such as a scheduler) with the same name, model, version and attributes.
Concurrent calls to get_or_create_source could thus each insert the same source (#2611).
This migration merges each group of such duplicates into its oldest source,
and replaces the constraint with a unique index on expressions that replace NULLs, so that NULLs count as equal, on any PostgreSQL version.
The index now also includes the source type, which every lookup of a source already filters on,
so that sources differing only in type are not merged.

Revision ID: 7c4e1a9d2b58
Revises: b63a02d5e184
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "7c4e1a9d2b58"
down_revision = "b63a02d5e184"
branch_labels = None
depends_on = None

PREVIOUS_CONSTRAINT_NAME = "data_source_name_key"
PREVIOUS_IDENTITY_COLUMNS = [
    "name",
    "user_id",
    "account_id",
    "model",
    "version",
    "attributes_hash",
]
INDEX_NAME = "data_source_identity_idx"
# A frozen copy of DATA_SOURCE_IDENTITY_EXPRESSIONS, as a migration should not depend on the current model.
IDENTITY_EXPRESSIONS = (
    "name",
    "coalesce(type, '')",
    "coalesce(user_id, -1)",
    "coalesce(account_id, -1)",
    "coalesce(model, '')",
    "coalesce(version, '')",
    "coalesce(attributes_hash, '\\x'::bytea)",
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
    op.drop_constraint(PREVIOUS_CONSTRAINT_NAME, "data_source", type_="unique")
    merged = merge_duplicate_sources(bind)
    op.execute(
        f"CREATE UNIQUE INDEX {INDEX_NAME} ON data_source ({', '.join(IDENTITY_EXPRESSIONS)})"
    )
    if merged:
        print(
            f"Merged {len(merged)} duplicate data source(s): "
            + ", ".join(
                f"{duplicate} into {keep}" for duplicate, keep in sorted(merged.items())
            )
            + ". Users referring to a merged data source by ID (for instance in API calls) should use the ID it was merged into."
        )


def downgrade():
    # Sources merged by the upgrade stay merged.
    op.drop_index(INDEX_NAME, table_name="data_source")
    op.create_unique_constraint(
        PREVIOUS_CONSTRAINT_NAME, "data_source", PREVIOUS_IDENTITY_COLUMNS
    )


def merge_duplicate_sources(bind) -> dict[int, int]:
    """Merge each group of identical data sources into the oldest one, moving over whatever references the newer ones.

    :returns: the ID of each merged data source, mapped to the ID of the data source it was merged into
    """
    merged: dict[int, int] = {}
    other_references = find_other_references(bind)
    while True:
        duplicates = bind.execute(sa.text(f"""
            SELECT keep, duplicate FROM (
                SELECT id AS duplicate, min(id) OVER (PARTITION BY {', '.join(IDENTITY_EXPRESSIONS)}) AS keep
                FROM data_source
            ) AS grouped
            WHERE duplicate <> keep
            ORDER BY keep, duplicate
            """)).all()
        if not duplicates:
            return merged
        mapping = {duplicate: keep for keep, duplicate in duplicates}
        merged.update(mapping)
        for keep, duplicate in duplicates:
            merge_source(bind, keep, duplicate, other_references)


def find_other_references(bind) -> list[tuple[str, str]]:
    """Find the foreign keys to data_source that are simply moved, including any that plugins added."""
    references = bind.execute(sa.text("""
        SELECT c.conrelid::regclass::text, a.attname
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        WHERE c.contype = 'f' AND c.confrelid = 'data_source'::regclass AND cardinality(c.conkey) = 1
        """)).all()
    return [
        (table, column)
        for table, column in references
        if (table, column) not in MERGED_REFERENCES
    ]


def merge_source(bind, keep: int, duplicate: int, other_references):
    """Merge the duplicate source into the kept one, and delete it."""
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
