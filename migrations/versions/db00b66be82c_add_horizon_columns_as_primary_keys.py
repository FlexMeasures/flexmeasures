"""add_horizon_columns_as_primary_keys

Revision ID: db00b66be82c
Revises: b087ce8b529f
Create Date: 2018-07-10 10:31:58.915035

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "db00b66be82c"
down_revision = "b087ce8b529f"
branch_labels = None
depends_on = None

"""
This revision adds the horizon field to the primary key of time series tables.
"""


def upgrade():
    # Power
    op.execute("alter table power drop constraint power_pkey;")
    op.alter_column(
        "power", "horizon", type_=sa.Interval, postgresql_using="horizon::interval"
    )
    op.execute(
        "alter table power add constraint power_pkey primary key (datetime, asset_id, horizon);"
    )
    # Price
    op.execute("alter table price drop constraint price_pkey;")
    op.alter_column(
        "price", "horizon", type_=sa.Interval, postgresql_using="horizon::interval"
    )
    op.execute(
        "alter table price add constraint price_pkey primary key (datetime, market_id, horizon);"
    )
    # Weather
    op.execute("alter table weather drop constraint weather_pkey;")
    op.alter_column(
        "weather", "horizon", type_=sa.Interval, postgresql_using="horizon::interval"
    )
    op.execute(
        "alter table weather add constraint weather_pkey primary key (datetime, sensor_id, horizon);"
    )


def downgrade():
    # Power
    op.execute("alter table power drop constraint power_pkey;")
    op.alter_column("price", "horizon", type_=sa.String(6))
    op.execute(
        "alter table power add constraint power_pkey primary key (datetime, asset_id);"
    )
    # Price
    op.execute("alter table price drop constraint price_pkey;")
    op.alter_column("price", "horizon", type_=sa.String(6))
    op.execute(
        "alter table price add constraint price_pkey primary key (datetime, market_id);"
    )
    # Weather
    op.execute("alter table weather drop constraint weather_pkey;")
    op.alter_column("weather", "horizon", type_=sa.String(6))
    op.execute(
        "alter table weather add constraint weather_pkey primary key (datetime, sensor_id);"
    )
