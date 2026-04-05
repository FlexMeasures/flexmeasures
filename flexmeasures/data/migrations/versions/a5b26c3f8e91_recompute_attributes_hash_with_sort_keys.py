"""Recompute attributes_hash on data_source with sort_keys=True

Previously the hash was computed without sorting JSON object keys, so a
PostgreSQL JSONB round-trip (which always returns keys in alphabetical order)
produced a different hash than the one stored in the database.  This caused
get_or_create_source() to silently create duplicate DataSource rows when it
was called with attributes that had been loaded back from the database.

Revision ID: a5b26c3f8e91
Revises: 8b62f8129f34
Create Date: 2026-04-05 12:00:00.000000

"""

import hashlib
import json

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
    """Recompute attributes_hash for all rows in data_source using sort_keys=True."""
    bind = op.get_bind()
    rows = bind.execute(
        text("SELECT id, attributes FROM data_source WHERE attributes IS NOT NULL")
    ).fetchall()

    for row_id, attributes in rows:
        if attributes is None:
            continue
        new_hash = _hash(attributes)
        bind.execute(
            text("UPDATE data_source SET attributes_hash = :h WHERE id = :id"),
            {"h": new_hash, "id": row_id},
        )


def downgrade():
    """Re-compute attributes_hash without sort_keys (restores pre-fix behaviour).

    Note: after downgrading, get_or_create_source() may again create duplicate
    DataSource rows for attributes loaded from the database.
    """
    bind = op.get_bind()
    rows = bind.execute(
        text("SELECT id, attributes FROM data_source WHERE attributes IS NOT NULL")
    ).fetchall()

    for row_id, attributes in rows:
        if attributes is None:
            continue
        old_hash = hashlib.sha256(json.dumps(attributes).encode("utf-8")).digest()
        bind.execute(
            text("UPDATE data_source SET attributes_hash = :h WHERE id = :id"),
            {"h": old_hash, "id": row_id},
        )
