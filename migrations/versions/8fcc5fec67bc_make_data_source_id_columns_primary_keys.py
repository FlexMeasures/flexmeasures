"""make_data_source_id_columns_primary_keys

Revision ID: 8fcc5fec67bc
Revises: 9c7fc8e46f1e
Create Date: 2018-07-30 15:39:30.583000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "8fcc5fec67bc"
down_revision = "9c7fc8e46f1e"
branch_labels = None
depends_on = None

"""
This revision adds the data_source_id field to the primary key of time series tables.
"""


def upgrade():

    # Power
    op.execute("alter table power drop constraint power_pkey;")
    op.execute(
        "alter table power add constraint power_pkey primary key (datetime, asset_id, horizon, data_source_id);"
    )
    # Price
    op.execute("alter table price drop constraint price_pkey;")
    op.execute(
        "alter table price add constraint price_pkey primary key (datetime, market_id, horizon, data_source_id);"
    )
    # Weather
    op.execute("alter table weather drop constraint weather_pkey;")
    op.execute(
        "alter table weather add constraint weather_pkey primary key (datetime, sensor_id, horizon, data_source_id);"
    )


def downgrade():

    # Power
    op.execute("alter table power drop constraint power_pkey;")
    op.execute(
        "alter table power add constraint power_pkey primary key (datetime, asset_id, horizon);"
    )
    # Price
    op.execute("alter table price drop constraint price_pkey;")
    op.execute(
        "alter table price add constraint price_pkey primary key (datetime, market_id, horizon;"
    )
    # Weather
    op.execute("alter table weather drop constraint weather_pkey;")
    op.execute(
        "alter table weather add constraint weather_pkey primary key (datetime, sensor_id, horizon);"
    )
