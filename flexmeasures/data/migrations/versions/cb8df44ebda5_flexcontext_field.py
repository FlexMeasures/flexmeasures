"""flexcontext field

Revision ID: cb8df44ebda5
Revises: 2ba59c7c954e
Create Date: 2024-12-16 18:39:34.168732

"""

from calendar import c
from turtle import update
from alembic import op
import attr
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "cb8df44ebda5"
down_revision = "2ba59c7c954e"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.add_column(sa.Column("flex_context", sa.JSON(), nullable=False))

    generic_asset_table = sa.Table(
        "generic_asset",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("attributes", sa.JSON),
        sa.Column("flex_context", sa.JSON),
        sa.Column("consumption_price_sensor_id", sa.Integer),
        sa.Column("production_price_sensor_id", sa.Integer),
    )

    inflexible_sensors_table = sa.Table(
        "asset_inflexible_sensors",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("generic_asset_id", sa.Integer),
        sa.Column("inflexible_sensor_id", sa.Integer),
    )

    # Initiate connection to execute the queries
    conn = op.get_bind()

    select_stmt = sa.select(
        [generic_asset_table.c.id, generic_asset_table.c.attributes]
    )
    results = conn.execute(select_stmt)

    for row in results:
        (
            asset_id,
            attributes_data,
            consumption_price_sensor_id,
            production_price_sensor_id,
        ) = row

        # fetch inflexible sensors
        select_stmt = sa.select(
            [inflexible_sensors_table.c.inflexible_sensor_id]
        ).where(inflexible_sensors_table.c.generic_asset_id == asset_id)
        inflexible_sensors = conn.execute(select_stmt)

        market_id = attributes_data.get("market_id")

        if consumption_price_sensor_id is None and market_id is not None:
            consumption_price_sensor_id = market_id

        flex_context = {
            "consumption-price": consumption_price_sensor_id,
            "production-price": production_price_sensor_id,
            "inflexible-sensors": [s[0] for s in inflexible_sensors],
        }

        update_stmt = (
            generic_asset_table.update()
            .where(generic_asset_table.c.id == asset_id)
            .values(flex_context=flex_context)
        )
        conn.execute(update_stmt)

    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("generic_asset_consumption_price_sensor_id_sensor_fkey"),
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            batch_op.f("generic_asset_production_price_sensor_id_sensor_fkey"),
            type_="foreignkey",
        )
        batch_op.drop_column("production_price_sensor_id")
        batch_op.drop_column("consumption_price_sensor_id")


def downgrade():
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("consumption_price_sensor_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("production_price_sensor_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            batch_op.f("generic_asset_production_price_sensor_id_sensor_fkey"),
            "sensor",
            ["production_price_sensor_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            batch_op.f("generic_asset_consumption_price_sensor_id_sensor_fkey"),
            "sensor",
            ["consumption_price_sensor_id"],
            ["id"],
            ondelete="SET NULL",
        )

    generic_asset_table = sa.Table(
        "generic_asset",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("flex_context", sa.JSON),
    )

    conn = op.get_bind()
    select_stmt = sa.select(
        [generic_asset_table.c.id, generic_asset_table.c.flex_context]
    )

    results = conn.execute(select_stmt)

    for row in results:
        asset_id, flex_context = row
        consumption_price_sensor_id = flex_context.get("consumption-price")
        production_price_sensor_id = flex_context.get("production-price")

        update_stmt = (
            generic_asset_table.update()
            .where(generic_asset_table.c.id == asset_id)
            .values(
                consumption_price_sensor_id=consumption_price_sensor_id,
                production_price_sensor_id=production_price_sensor_id,
            )
        )
        conn.execute(update_stmt)

    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.drop_column("flex_context")
