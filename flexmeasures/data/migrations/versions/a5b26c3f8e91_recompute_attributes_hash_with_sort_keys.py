"""Recompute attributes_hash on data_source with sort_keys=True

Previously the hash was computed without sorting JSON object keys, so a
PostgreSQL JSONB round-trip (which always returns keys in alphabetical order)
produced a different hash than the one stored in the database.  This caused
get_or_create_source() to silently create duplicate DataSource rows when it
was called with attributes that had been loaded back from the database.

The upgrade also handles the case where the bug already produced duplicate rows
(same logical content, but saved with different key-insertion-order hashes).
For each group of duplicates the newest row (highest ID) is kept as-is.  Older
duplicates receive a synthetic ``{"flexmeasures-hash-conflict": N}`` attribute
so that their hashes remain unique without touching the timed_belief table.

Downgrade note: since PostgreSQL JSONB already serialises all object keys in
alphabetical order when storing, ``json.dumps(attrs)`` and
``json.dumps(attrs, sort_keys=True)`` produce identical strings for any data
that has gone through JSONB.  Therefore recomputing the hash without
``sort_keys`` would yield the same bytes as the upgrade, making a downgrade
data-migration a no-op.  The downgrade function is intentionally left empty.

Revision ID: a5b26c3f8e91
Revises: 8b62f8129f34
Create Date: 2026-04-05 12:00:00.000000

"""

import hashlib
import json
from collections import defaultdict

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "a5b26c3f8e91"
down_revision = "8b62f8129f34"
branch_labels = None
depends_on = None


def _hash(attributes: dict) -> bytes:
    return hashlib.sha256(
        json.dumps(attributes, sort_keys=True).encode("utf-8")
    ).digest()


def upgrade():
    """Recompute attributes_hash for all rows in data_source using sort_keys=True.

    Duplicate rows (same logical content, different key-order hashes) are
    resolved by tagging older rows with a synthetic conflict-marker attribute so
    that each row still gets a unique hash.  The newest row (highest id) is
    always kept clean.
    """
    bind = op.get_bind()
    rows = bind.execute(
        text(
            "SELECT id, name, user_id, model, version, attributes "
            "FROM data_source "
            "WHERE attributes IS NOT NULL"
        )
    ).fetchall()

    # Group rows by their normalised unique key (name, user_id, model, version,
    # sorted-attributes hash).  Any group with >1 member means the bug created
    # duplicate rows.
    groups: dict = defaultdict(list)
    attrs_by_id: dict = {}
    for row_id, name, user_id, model, version, attributes in rows:
        if attributes is None:
            continue
        attrs_by_id[row_id] = attributes
        key = (name, user_id, model, version, _hash(attributes))
        groups[key].append(row_id)

    # Resolve duplicates: for groups with more than one member, keep the newest
    # (highest id) intact and mark the rest with a conflict counter attribute.
    conflict_attrs: dict = {}  # row_id -> modified attributes
    for key, ids in groups.items():
        if len(ids) <= 1:
            continue
        # Sort ascending so we can mark older rows (all except the last/highest)
        ids_sorted = sorted(ids)
        for conflict_index, row_id in enumerate(ids_sorted[:-1], start=1):
            modified = dict(attrs_by_id[row_id])
            modified["flexmeasures-hash-conflict"] = conflict_index
            conflict_attrs[row_id] = modified

    # Apply updates: write modified attributes + new hash for conflict rows,
    # and new hash only for clean rows.
    for row_id, attributes in attrs_by_id.items():
        if row_id in conflict_attrs:
            new_attrs = conflict_attrs[row_id]
            bind.execute(
                text(
                    "UPDATE data_source "
                    "SET attributes = :a, attributes_hash = :h "
                    "WHERE id = :id"
                ),
                {"a": json.dumps(new_attrs), "h": _hash(new_attrs), "id": row_id},
            )
        else:
            bind.execute(
                text("UPDATE data_source SET attributes_hash = :h WHERE id = :id"),
                {"h": _hash(attributes), "id": row_id},
            )


def downgrade():
    """No data migration needed on downgrade.

    PostgreSQL JSONB always serialises object keys in alphabetical order when
    storing.  This means ``json.dumps(attrs)`` and
    ``json.dumps(attrs, sort_keys=True)`` produce identical strings for any
    attributes that have been round-tripped through the database, so
    recomputing hashes without ``sort_keys`` would yield the same bytes.

    Note: rows that were tagged with ``flexmeasures-hash-conflict`` during
    upgrade are NOT cleaned up here, because doing so would require knowing
    which rows were duplicates and which one was the "canonical" row -- that
    information is not reliably recoverable.  After a downgrade, those rows
    will have a slightly different ``attributes`` dict than before the upgrade,
    but ``get_or_create_source`` will still find them correctly via their hash.
    """
    pass
