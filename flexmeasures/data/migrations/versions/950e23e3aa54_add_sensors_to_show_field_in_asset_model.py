"""add sensors_to_show field in asset model

Revision ID: 950e23e3aa54
Revises: 0af134879301
Create Date: 2024-09-27 10:21:37.910186

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import select

# revision identifiers, used by Alembic.
revision = "950e23e3aa54"
down_revision = "0af134879301"
branch_labels = None
depends_on = None


def upgrade():
    # Add the 'sensors_to_show' column with nullable=True since we will populate it
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sensors_to_show", sa.JSON(), nullable=True))

    generic_asset_table = sa.Table(
        "generic_asset",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("attributes", sa.JSON),
        sa.Column("sensors_to_show", sa.JSON),
    )

    # Initiate connection to execute the queries
    conn = op.get_bind()

    select_stmt = select(generic_asset_table.c.id, generic_asset_table.c.attributes)
    results = conn.execute(select_stmt)

    for row in results:
        asset_id, attributes_data = row

        sensors_to_show = attributes_data.get("sensors_to_show", [])

        if not isinstance(sensors_to_show, list):
            sensors_to_show = [sensors_to_show]

        update_stmt = (
            generic_asset_table.update()
            .where(generic_asset_table.c.id == asset_id)
            .values(sensors_to_show=sensors_to_show)
        )
        conn.execute(update_stmt)

    # After populating column, set back to be NOT NULL
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.alter_column("sensors_to_show", nullable=False)


def downgrade():
    conn = op.get_bind()

    generic_asset_table = sa.Table(
        "generic_asset",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("attributes", sa.JSON),
        sa.Column("sensors_to_show", sa.JSON),
    )

    select_stmt = select(
        generic_asset_table.c.id,
        generic_asset_table.c.sensors_to_show,
        generic_asset_table.c.attributes,
    )
    results = conn.execute(select_stmt)

    for row in results:
        asset_id, sensors_to_show_data, attributes_data = row

        if attributes_data is None:
            attributes_data = {}

        attributes_data["sensors_to_show"] = sensors_to_show_data

        update_stmt = (
            generic_asset_table.update()
            .where(generic_asset_table.c.id == asset_id)
            .values(attributes=attributes_data)
        )
        conn.execute(update_stmt)

    # After migrating data back to the attributes field, drop the sensors_to_show column
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.drop_column("sensors_to_show")
