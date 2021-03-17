"""add_soc_columns_in_asset_table

Revision ID: 61bfc6e45c4d
Revises: 1a4f0e5c4b86
Create Date: 2018-09-10 11:10:34.068000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "61bfc6e45c4d"
down_revision = "1a4f0e5c4b86"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("asset", sa.Column("min_soc_in_mwh", sa.Float(), nullable=True))
    op.add_column("asset", sa.Column("max_soc_in_mwh", sa.Float(), nullable=True))
    op.add_column("asset", sa.Column("soc_in_mwh", sa.Float(), nullable=True))
    op.add_column(
        "asset", sa.Column("soc_datetime", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    op.drop_column("asset", "min_soc_in_mwh")
    op.drop_column("asset", "max_soc_in_mwh")
    op.drop_column("asset", "soc_in_mwh")
    op.drop_column("asset", "soc_datetime")
