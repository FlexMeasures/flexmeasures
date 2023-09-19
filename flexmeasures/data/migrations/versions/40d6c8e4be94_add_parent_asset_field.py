"""empty message

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
            "parent_generic_asset_id", sa.INTEGER, sa.ForeignKey("generic_asset.id")
        ),
    )


def downgrade():
    op.drop_column("generic_asset", "parent_generic_asset_id")
