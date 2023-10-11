"""Delete children assets on cascade when deleting an asset.

Revision ID: a60cc43aef5e
Revises: ac5e340cccea
Create Date: 2023-10-11 14:04:19.447773

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "a60cc43aef5e"
down_revision = "ac5e340cccea"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        "generic_asset_parent_asset_id_generic_asset_fkey",
        "generic_asset",
        type_="foreignkey",
    )
    op.create_foreign_key(
        None,
        "generic_asset",
        "generic_asset",
        ["parent_asset_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade():
    op.drop_constraint(
        "generic_asset_parent_asset_id_generic_asset_fkey",
        "generic_asset",
        type_="foreignkey",
    )
    op.create_foreign_key(
        None,
        "generic_asset",
        "generic_asset",
        ["parent_asset_id"],
        ["id"],
    )
