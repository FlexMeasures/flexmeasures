"""rename_data_source_columns_in_power_price_and_weather_tables

Revision ID: 2c9a32614784
Revises: e0c2f9aff251
Create Date: 2018-07-26 15:58:07.780000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "2c9a32614784"
down_revision = "e0c2f9aff251"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("price", "data_source", new_column_name="data_source_id")
    op.alter_column("power", "data_source", new_column_name="data_source_id")
    op.alter_column("weather", "data_source", new_column_name="data_source_id")


def downgrade():
    op.alter_column("price", "data_source_id", new_column_name="data_source")
    op.alter_column("power", "data_source_id", new_column_name="data_source")
    op.alter_column("weather", "data_source_id", new_column_name="data_source")
