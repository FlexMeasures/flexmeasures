"""Allow duplicate root asset names.

Revision ID: c7b7f9019d4b
Revises: b2c3d4e5f6a7
Create Date: 2026-06-05 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c7b7f9019d4b"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        "generic_asset_name_parent_asset_id_key", "generic_asset", type_="unique"
    )
    op.create_index(
        "generic_asset_name_parent_asset_id_key",
        "generic_asset",
        ["name", "parent_asset_id"],
        unique=True,
        postgresql_where=sa.text("parent_asset_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("generic_asset_name_parent_asset_id_key", table_name="generic_asset")
    op.create_unique_constraint(
        "generic_asset_name_parent_asset_id_key",
        "generic_asset",
        ["name", "parent_asset_id"],
    )
