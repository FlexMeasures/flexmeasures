"""flexcontext field

Revision ID: cb8df44ebda5
Revises: 2ba59c7c954e
Create Date: 2024-12-16 18:39:34.168732

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "cb8df44ebda5"
down_revision = "2ba59c7c954e"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.add_column(sa.Column("flex_context", sa.JSON(), nullable=True))

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
        "assets_inflexible_sensors",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("generic_asset_id", sa.Integer),
        sa.Column("inflexible_sensor_id", sa.Integer),
    )

    # Initiate connection to execute the queries
    conn = op.get_bind()

    select_stmt = sa.select(
        generic_asset_table.c.id,
        generic_asset_table.c.attributes,
        generic_asset_table.c.consumption_price_sensor_id,
        generic_asset_table.c.production_price_sensor_id,
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
        select_stmt = sa.select(inflexible_sensors_table.c.inflexible_sensor_id).where(
            inflexible_sensors_table.c.generic_asset_id == asset_id
        )
        inflexible_device_sensors = conn.execute(select_stmt)

        market_id = attributes_data.get("market_id")
        attributes_data.pop("market_id", None)

        if consumption_price_sensor_id is None and market_id is not None:
            consumption_price_sensor_id = market_id

        flex_context = {
            "consumption-price": {"sensor": consumption_price_sensor_id},
            "production-price": {"sensor": production_price_sensor_id},
            "inflexible-device-sensors": [s[0] for s in inflexible_device_sensors],
        }

        update_stmt = (
            generic_asset_table.update()
            .where(generic_asset_table.c.id == asset_id)
            .values(flex_context=flex_context, attributes=attributes_data)
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

    # Drop foreign key constraints first
    op.drop_constraint(
        "assets_inflexible_sensors_generic_asset_id_generic_asset_fkey",
        "assets_inflexible_sensors",
        type_="foreignkey",
    )
    op.drop_constraint(
        "assets_inflexible_sensors_inflexible_sensor_id_sensor_fkey",
        "assets_inflexible_sensors",
        type_="foreignkey",
    )

    # Drop the table
    op.drop_table("assets_inflexible_sensors")


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

    # Create assets_inflexible_sensors table
    op.create_table(
        "assets_inflexible_sensors",
        sa.Column("generic_asset_id", sa.Integer(), nullable=False),
        sa.Column("inflexible_sensor_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["generic_asset_id"],
            ["generic_asset.id"],
            name="assets_inflexible_sensors_generic_asset_id_generic_asset_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["inflexible_sensor_id"],
            ["sensor.id"],
            name="assets_inflexible_sensors_inflexible_sensor_id_sensor_fkey",
        ),
        sa.PrimaryKeyConstraint(
            "generic_asset_id",
            "inflexible_sensor_id",
            name="assets_inflexible_sensors_pkey",
        ),
        sa.UniqueConstraint(
            "inflexible_sensor_id",
            "generic_asset_id",
            name="assets_inflexible_sensors_key",
        ),
    )

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
        "assets_inflexible_sensors",
        sa.MetaData(),
        sa.Column("generic_asset_id", sa.Integer),
        sa.Column("inflexible_sensor_id", sa.Integer),
    )

    conn = op.get_bind()
    select_stmt = sa.select(
        generic_asset_table.c.id,
        generic_asset_table.c.flex_context,
        generic_asset_table.c.attributes,
    )

    results = conn.execute(select_stmt)

    for row in results:
        asset_id, flex_context, attributes_data = row
        consumption_price_sensor_id = (
            flex_context.get("consumption-price")["sensor"]
            if flex_context.get("consumption-price")
            else None
        )
        production_price_sensor_id = (
            flex_context.get("production-price")["sensor"]
            if flex_context.get("production-price")
            else None
        )

        market_id = consumption_price_sensor_id
        attributes_data["market_id"] = market_id

        update_stmt = (
            generic_asset_table.update()
            .where(generic_asset_table.c.id == asset_id)
            .values(
                consumption_price_sensor_id=consumption_price_sensor_id,
                production_price_sensor_id=production_price_sensor_id,
                attributes=attributes_data,
            )
        )
        conn.execute(update_stmt)

        for sensor_id in flex_context.get("inflexible-device-sensors", []):
            insert_stmt = inflexible_sensors_table.insert().values(
                generic_asset_id=asset_id, inflexible_sensor_id=sensor_id
            )
            conn.execute(insert_stmt)

    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.drop_column("flex_context")
