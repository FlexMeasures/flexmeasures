"""Add parent_asset_id column.

Revision ID: 40d6c8e4be94
Revises: 2ac7fb39ce0c
Create Date: 2023-09-19 17:05:00.020779

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "40d6c8e4be94"
down_revision = "2ac7fb39ce0c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "generic_asset",
        sa.Column(
            "parent_asset_id",
            sa.INTEGER,
            sa.ForeignKey("generic_asset.id"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "self_reference", "generic_asset", "parent_asset_id != id"
    )


def downgrade():
    connection = op.get_bind()
    number_assets_with_parent = connection.execute(
        "SELECT COUNT(*) from generic_asset WHERE parent_asset_id is not null;"
    ).fetchone()[0]
    print(
        f"Dropping column `parent_asset_id` from the table `generic_asset`. Currently, the database contains {number_assets_with_parent} asset/s that have a parent asset defined, beware that this information will be gone."
    )
    op.drop_constraint("self_reference", "generic_asset", type_="check")
    op.drop_column("generic_asset", "parent_asset_id")
