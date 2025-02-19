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


def build_flex_context(
    attributes_data,
    consumption_price_sensor_id,
    market_id,
    production_price_sensor_id,
    inflexible_device_sensors,
    capacity_in_mw,
    consumption_capacity_in_mw,
    production_capacity_in_mw,
    ems_peak_consumption_price,
    ems_peak_production_price,
    ems_consumption_breach_price,
    ems_production_breach_price,
):

    keys_to_remove = [
        "market_id",
        "capacity_in_mw",
        "consumption_capacity_in_mw",
        "production_capacity_in_mw",
        "ems_peak_consumption_price",
        "ems_peak_production_price",
        "ems_consumption_breach_price",
        "ems_production_breach_price",
        # Adding the below since these field could have been saved as either the hyphen or underscore format
        "ems-peak-consumption-price",
        "ems-peak-production-price",
        "ems-consumption-breach-price",
        "ems-production-breach-price",
    ]
    for key in keys_to_remove:
        attributes_data.pop(key, None)

    flex_context = {
        "consumption-price": {
            "sensor": (
                consumption_price_sensor_id
                if consumption_price_sensor_id
                else market_id
            )
        },
        "production-price": {"sensor": production_price_sensor_id},
        "inflexible-device-sensors": [s[0] for s in inflexible_device_sensors],
    }

    capacity_data = {
        "site-power-capacity": capacity_in_mw,
        "site-consumption-capacity": consumption_capacity_in_mw,
        "site-production-capacity": production_capacity_in_mw,
    }
    for key, value in capacity_data.items():
        if value is not None:
            flex_context[key] = f"{int(value * 1000)} KW"

    price_data = {
        "site-peak-consumption-price": ems_peak_consumption_price,
        "site-peak-production-price": ems_peak_production_price,
        "site-consumption-breach-price": ems_consumption_breach_price,
        "site-production-breach-price": ems_production_breach_price,
    }
    for key, value in price_data.items():
        if value is not None:
            flex_context[key] = value

    return flex_context


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

        # Get fields-to-migrate from attrubutes
        market_id = attributes_data.get("market_id")
        capacity_in_mw = attributes_data.get("capacity_in_mw")
        consumption_capacity_in_mw = attributes_data.get("consumption_capacity_in_mw")
        production_capacity_in_mw = attributes_data.get("production_capacity_in_mw")
        ems_peak_consumption_price = attributes_data.get(
            "ems_peak_consumption_price"
        ) or attributes_data.get("ems-peak-consumption-price")
        ems_peak_production_price = attributes_data.get(
            "ems_peak_production_price"
        ) or attributes_data.get("ems-peak-production-price")
        ems_consumption_breach_price = attributes_data.get(
            "ems_consumption_breach_price"
        ) or attributes_data.get("ems-consumption-breach-price")
        ems_production_breach_price = attributes_data.get(
            "ems_production_breach_price"
        ) or attributes_data.get("ems-production-breach-price")

        # Build flex context - code off-loaded to external function as it is too long
        flex_context = build_flex_context(
            attributes_data,
            consumption_price_sensor_id,
            market_id,
            production_price_sensor_id,
            inflexible_device_sensors,
            capacity_in_mw,
            consumption_capacity_in_mw,
            production_capacity_in_mw,
            ems_peak_consumption_price,
            ems_peak_production_price,
            ems_consumption_breach_price,
            ems_production_breach_price,
        )

        cleaned_flex_context = {}

        # loop through flex_context and remove keys with null values or empty arrays
        for key, value in flex_context.items():
            if (
                value
                and (isinstance(value, dict) or isinstance(value, list))
                or isinstance(value, str)
            ):
                if isinstance(value, dict) and value.get("sensor") is not None:
                    cleaned_flex_context[key] = value
                elif isinstance(value, list) and len(value) > 0:
                    cleaned_flex_context[key] = value
                elif isinstance(value, str) and (value != "" or value is not None):
                    cleaned_flex_context[key] = value

        flex_context = cleaned_flex_context

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
        capacity_in_mw = (
            flex_context.get("site-power-capacity")
            if flex_context.get("site-power-capacity")
            else None
        )
        consumption_capacity_in_mw = (
            flex_context.get("site-consumption-capacity")
            if flex_context.get("site-consumption-capacity")
            else None
        )
        production_capacity_in_mw = (
            flex_context.get("site-production-capacity")
            if flex_context.get("site-production-capacity")
            else None
        )
        ems_peak_consumption_price = (
            flex_context.get("site-peak-consumption-price")
            if flex_context.get("site-peak-consumption-price")
            else None
        )
        ems_peak_production_price = (
            flex_context.get("site-peak-production-price")
            if flex_context.get("site-peak-production-price")
            else None
        )
        ems_consumption_breach_price = (
            flex_context.get("site-consumption-breach-price")
            if flex_context.get("site-consumption-breach-price")
            else None
        )
        ems_production_breach_price = (
            flex_context.get("site-production-breach-price")
            if flex_context.get("site-production-breach-price")
            else None
        )

        if capacity_in_mw is not None:
            capacity_in_mw = float(capacity_in_mw.replace(" KW", "")) / 1000

        if consumption_capacity_in_mw is not None:
            consumption_capacity_in_mw = (
                float(consumption_capacity_in_mw.replace(" KW", "")) / 1000
            )

        if production_capacity_in_mw is not None:
            production_capacity_in_mw = (
                float(production_capacity_in_mw.replace(" KW", "")) / 1000
            )

        attributes_data["market_id"] = market_id
        attributes_data["capacity_in_mw"] = capacity_in_mw
        attributes_data["consumption_capacity_in_mw"] = consumption_capacity_in_mw
        attributes_data["production_capacity_in_mw"] = production_capacity_in_mw
        attributes_data["ems_peak_consumption_price"] = ems_peak_consumption_price
        attributes_data["ems_peak_production_price"] = ems_peak_production_price
        attributes_data["ems_consumption_breach_price"] = ems_consumption_breach_price
        attributes_data["ems_production_breach_price"] = ems_production_breach_price

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
