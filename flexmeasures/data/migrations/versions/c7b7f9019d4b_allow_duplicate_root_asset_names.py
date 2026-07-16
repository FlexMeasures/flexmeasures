"""Allow duplicate root asset names.

Revision ID: c7b7f9019d4b
Revises: b2c3d4e5f6a7
Create Date: 2026-06-05 12:00:00.000000

"""

import sys

from alembic import op, context
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c7b7f9019d4b"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


class DuplicateRootAssetNamesError(Exception):
    """Raised (instead of RuntimeError) so flask_migrate's `catch_errors` decorator
    doesn't swallow it into a silent `sys.exit(1)` — it specifically catches
    RuntimeError and CommandError and logs via a logger flexmeasures doesn't surface,
    which hid this error entirely on first use. See flask_migrate/__init__.py's
    `catch_errors`. Anything else propagates as a normal traceback instead."""


def _rename_duplicate_root_assets(connection, auto_rename: bool):
    """Find root assets (no parent) sharing (account_id, name), which the new
    partial unique index below would reject.

    If auto_rename is False, raise with a report of which assets collide, so the
    operator can decide what to do. If True, keep the lowest-id asset's name as-is
    and suffix the others with " (2)", " (3)", etc., ordered by id.
    """
    duplicates = connection.execute(
        sa.text(
            """
            SELECT id, account_id, name
            FROM generic_asset
            WHERE parent_asset_id IS NULL
              AND account_id IS NOT NULL
              AND (account_id, name) IN (
                  SELECT account_id, name
                  FROM generic_asset
                  WHERE parent_asset_id IS NULL AND account_id IS NOT NULL
                  GROUP BY account_id, name
                  HAVING COUNT(*) > 1
              )
            ORDER BY account_id, name, id
            """
        )
    ).fetchall()

    if not duplicates:
        return

    if not auto_rename:
        details = "\n".join(
            f"  - id={row.id}, account_id={row.account_id}, name={row.name!r}"
            for row in duplicates
        )
        message = (
            "Cannot upgrade: multiple root assets (no parent) share the same "
            "name within the same account, which the new unique index forbids.\n"
            f"Affected assets:\n{details}\n\n"
            "Rerun this migration with `-x rename_duplicate_root_assets=true` "
            "(e.g. `flexmeasures db upgrade -x rename_duplicate_root_assets=true`) "
            "to automatically rename the duplicates, keeping the lowest-id asset's "
            "name unchanged and suffixing the others with ' (2)', ' (3)', etc. "
            "Alternatively, rename them yourself first and rerun `flexmeasures db upgrade`."
        )
        print(message, file=sys.stderr, flush=True)
        raise DuplicateRootAssetNamesError(message)

    seen: dict[tuple, int] = {}
    for row in duplicates:
        key = (row.account_id, row.name)
        seen[key] = seen.get(key, 0) + 1
        occurrence = seen[key]
        if occurrence == 1:
            continue  # lowest-id asset keeps its original name
        connection.execute(
            sa.text("UPDATE generic_asset SET name = :name WHERE id = :id"),
            {"name": f"{row.name} ({occurrence})", "id": row.id},
        )


def upgrade():
    auto_rename = context.get_x_argument(as_dictionary=True).get(
        "rename_duplicate_root_assets", "false"
    ).lower() in ("true", "1", "yes")
    _rename_duplicate_root_assets(op.get_bind(), auto_rename)

    op.drop_constraint(
        "generic_asset_name_parent_asset_id_key",
        "generic_asset",
        type_="unique",
        if_exists=True,
    )
    op.drop_index(
        "generic_asset_name_parent_asset_id_key",
        table_name="generic_asset",
        if_exists=True,
    )
    op.create_index(
        "generic_asset_name_parent_asset_id_key",
        "generic_asset",
        ["name", "parent_asset_id"],
        unique=True,
        postgresql_where=sa.text("parent_asset_id IS NOT NULL"),
        sqlite_where=sa.text("parent_asset_id IS NOT NULL"),
    )
    op.create_index(
        "generic_asset_root_account_id_name_key",
        "generic_asset",
        ["account_id", "name"],
        unique=True,
        postgresql_where=sa.text("parent_asset_id IS NULL AND account_id IS NOT NULL"),
        sqlite_where=sa.text("parent_asset_id IS NULL AND account_id IS NOT NULL"),
    )
    op.create_index(
        "generic_asset_public_root_name_key",
        "generic_asset",
        ["name"],
        unique=True,
        postgresql_where=sa.text("parent_asset_id IS NULL AND account_id IS NULL"),
        sqlite_where=sa.text("parent_asset_id IS NULL AND account_id IS NULL"),
    )


def downgrade():
    op.drop_index(
        "generic_asset_public_root_name_key",
        table_name="generic_asset",
        if_exists=True,
    )
    op.drop_index(
        "generic_asset_root_account_id_name_key",
        table_name="generic_asset",
        if_exists=True,
    )
    op.drop_index(
        "generic_asset_name_parent_asset_id_key",
        table_name="generic_asset",
        if_exists=True,
    )
    op.create_unique_constraint(
        "generic_asset_name_parent_asset_id_key",
        "generic_asset",
        ["name", "parent_asset_id"],
    )
