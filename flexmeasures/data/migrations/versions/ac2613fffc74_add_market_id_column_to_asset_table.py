"""add_market_id_column_to_asset_table

Revision ID: ac2613fffc74
Revises: 50cf294e007d
Create Date: 2018-10-23 15:49:36.312000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ac2613fffc74"
down_revision = "50cf294e007d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("asset", sa.Column("market_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "asset_market_id_market_fkey", "asset", "market", ["market_id"], ["id"]
    )
    op.execute(
        """
        update asset set market_id = market.id from market where market.name = 'kpx_da';
        """
    )


def downgrade():
    op.drop_constraint("asset_market_id_market_fkey", "asset", type_="foreignkey")
    op.drop_column("asset", "market_id")
