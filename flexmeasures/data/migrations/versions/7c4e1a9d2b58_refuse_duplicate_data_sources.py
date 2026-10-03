"""Refuse duplicate data sources, after merging any that exist.

The unique constraint on data_source treated NULL values as distinct,
so it never refused a second source without a user or account (such as a scheduler) with the same name, model, version and attributes.
Concurrent calls to get_or_create_source could thus each insert the same source (#2611).
This migration merges each group of such duplicates into its oldest source,
and replaces the constraint with a unique index on expressions that replace NULLs, so that NULLs count as equal, on any PostgreSQL version.
The index now also includes the source type, which every lookup of a source already filters on,
so that sources differing only in type are not merged.

Where source IDs are stored in JSON (such as the sources a sensor reference in a flex-context filters on),
references to a merged source are pointed at the source it was merged into.
Jobs waiting in Redis cannot be updated this way; ``flexmeasures jobs check-source-references`` lists them.

This runs after the migration that couples each data source to the organisation it records for (c5e1a7b94d20),
and the order matters: that one fills in ``account_id``, which the unique index below treats as part of a source's identity.
Two organisations running the same data generator under the same configuration are therefore left alone here,
where before they would have looked like duplicates of one another and been merged into a single source.

Revision ID: 7c4e1a9d2b58
Revises: c5e1a7b94d20
"""

from __future__ import annotations

import hashlib
import json

from alembic import op
import sqlalchemy as sa

revision = "7c4e1a9d2b58"
down_revision = "c5e1a7b94d20"
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

# JSON columns that can store source IDs, with a condition selecting the rows that still describe work to be done.
# Records of what already happened, such as automation runs, keep the IDs they were made with.
JSON_REFERENCE_COLUMNS = [
    ("generic_asset", "flex_context", None),
    ("generic_asset", "flex_model", None),
    ("generic_asset", "attributes", None),
    ("sensor", "attributes", None),
    ("automation", "parameters", None),
    ("automation_run_job", "payload", "status = 'pending'"),
    ("data_source", "attributes", None),
]

# Keys holding a list of source IDs, and the key holding a single source ID next to a "sensor" key (in reporter inputs).
SOURCE_LIST_KEYS = ("sources", "user_source_ids")
SOURCE_KEY = "source"


def upgrade():
    bind = op.get_bind()
    # Drop the previous constraint first, so that recomputing an attributes hash below cannot trip over it.
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
            + ". Jobs waiting in Redis may still refer to the merged data sources by ID, and would then fail. "
            "List them with `flexmeasures jobs check-source-references`. "
            "Users referring to a merged data source by ID (for instance in API calls) should use the ID it was merged into."
        )


def downgrade():
    # Sources merged by the upgrade stay merged, and references to them stay pointed at the sources they were merged into.
    op.drop_index(INDEX_NAME, table_name="data_source")
    op.create_unique_constraint(
        PREVIOUS_CONSTRAINT_NAME, "data_source", PREVIOUS_IDENTITY_COLUMNS
    )


def merge_duplicate_sources(bind) -> dict[int, int]:
    """Merge each group of identical data sources into the oldest one, moving over whatever references the newer ones.

    Pointing stored references at the oldest source can change the attributes of a data source that records such references,
    making it identical to another data source, so this repeats until no duplicates remain.

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
        # A source merged in an earlier round may itself be referred to by the ID of a source merged before it.
        merged = {
            duplicate: mapping.get(keep, keep) for duplicate, keep in merged.items()
        }
        merged.update(mapping)
        remap_json_references(bind, mapping)
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


def remap_json_references(bind, mapping: dict[int, int]):
    """Point source IDs stored in JSON columns at the sources their sources are merged into.

    When the attributes of a data source change, its attributes hash is recomputed,
    unless the hash did not match its attributes to begin with (attributes set after its creation are not hashed).
    """
    for table, column, condition in JSON_REFERENCE_COLUMNS:
        hash_column = ", attributes_hash" if table == "data_source" else ""
        where = f"({column}::text LIKE '%\"source%' OR {column}::text LIKE '%\"user_source_ids\"%')"
        if condition:
            where += f" AND {condition}"
        rows = bind.execute(
            sa.text(f"SELECT id, {column}{hash_column} FROM {table} WHERE {where}")
        ).all()
        remapped = 0
        for row in rows:
            value = row[1]
            new_value = remap_source_ids(value, mapping)
            if new_value == value:
                continue
            params = dict(id=row[0], value=json.dumps(new_value))
            assignments = f"{column} = CAST(:value AS jsonb)"
            if table == "data_source":
                old_hash = bytes(row[2]) if row[2] is not None else None
                if old_hash == hash_attributes(value):
                    params["hash"] = hash_attributes(new_value)
                    assignments += ", attributes_hash = :hash"
            bind.execute(
                sa.text(f"UPDATE {table} SET {assignments} WHERE id = :id"), params
            )
            remapped += 1
        if remapped:
            print(
                f"Pointed source IDs in {table}.{column} at the data sources they were merged into, in {remapped} row(s)."
            )


def remap_source_ids(value, mapping: dict[int, int]):
    """Return a copy of a JSON value, with the source IDs it holds mapped."""
    if isinstance(value, list):
        return [remap_source_ids(item, mapping) for item in value]
    if not isinstance(value, dict):
        return value
    remapped = {}
    for key, item in value.items():
        if key in SOURCE_LIST_KEYS and isinstance(item, list):
            ids = [
                mapping.get(i, i) if is_id(i) else remap_source_ids(i, mapping)
                for i in item
            ]
            # Two sources merged into one leave one reference.
            remapped[key] = [
                i for n, i in enumerate(ids) if not is_id(i) or i not in ids[:n]
            ]
        elif key == SOURCE_KEY and "sensor" in value and is_id(item):
            remapped[key] = mapping.get(item, item)
        else:
            remapped[key] = remap_source_ids(item, mapping)
    return remapped


def is_id(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def hash_attributes(attributes: dict) -> bytes:
    """A frozen copy of DataSource.hash_attributes."""
    return hashlib.sha256(
        json.dumps(attributes, sort_keys=True).encode("utf-8")
    ).digest()
