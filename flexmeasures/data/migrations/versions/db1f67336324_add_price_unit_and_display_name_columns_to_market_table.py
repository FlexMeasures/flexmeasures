"""add_price_unit_and_display_name_columns_to_market_table

Revision ID: db1f67336324
Revises: 3e43d3274d16
Create Date: 2018-10-07 13:50:23.690000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "db1f67336324"
down_revision = "3e43d3274d16"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "market",
        sa.Column(
            "display_name", sa.String(length=80), nullable=False, server_default=""
        ),
    )
    op.execute(
        """
        update market set display_name = 'EPEX SPOT day-ahead market' where name = 'epex_da';
        update market set display_name = 'KPX day-ahead market' where name = 'kpx_da';
        """
    )
    op.create_unique_constraint("market_display_name_key", "market", ["display_name"])
    op.add_column(
        "market",
        sa.Column(
            "price_unit", sa.String(length=80), nullable=False, server_default=""
        ),
    )
    op.execute(
        """
        update market set price_unit = 'EUR/MWh' where name = 'epex_da';
        update market set price_unit = 'KRW/kWh' where name = 'kpx_da';
        """
    )


def downgrade():
    op.drop_column("market", "price_unit")
    op.drop_constraint("market_display_name_key", "market", type_="unique")
    op.drop_column("market", "display_name")
