"""flexcontext field

Revision ID: cb8df44ebda5
Revises: 2ba59c7c954e
Create Date: 2024-12-16 18:39:34.168732

"""

from alembic import op
import json
import sqlalchemy as sa

from flexmeasures.utils.unit_utils import is_power_unit, is_capacity_price_unit, ur

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
        # Alt keys when values are stored as a fixed value
        "site-power-capacity",
        "site-consumption-capacity",
        "site-production-capacity",
        "site-peak-consumption-price",
        "site-peak-production-price",
        "site-consumption-breach-price",
        "site-production-breach-price",
        # Adding the below since these field could have been saved as either the hyphen or underscore format
        "ems-peak-consumption-price",
        "ems-peak-production-price",
        "ems-consumption-breach-price",
        "ems-production-breach-price",
    ]
    for key in keys_to_remove:
        attributes_data.pop(key, None)

    flex_context = attributes_data.pop("flex-context", None)
    if flex_context is None:
        flex_context = {}
    else:
        flex_context = json.loads(flex_context)

    # Fill the flex-context's consumption-price field with:
    # - the value of the consumption_price_sensor_id column
    # - otherwise, the market_id attribute (old fallback)
    # - otherwise, keep the consumption-price field from the flex-context attribute
    if (
        consumption_price_sensor_id is not None
        or market_id is not None
        or "consumption-price" not in flex_context
    ):
        flex_context["consumption-price"] = {
            "sensor": (
                consumption_price_sensor_id
                if consumption_price_sensor_id
                else market_id
            )
        }

    # Fill the flex-context's production-price field with:
    # - the value of the production_price_sensor_id column
    # - otherwise, the market_id attribute (old fallback, also for the production sensor)
    # - otherwise, keep the production-price field from the flex-context attribute
    if (
        production_price_sensor_id is not None
        or market_id is not None
        or "production-price" not in flex_context
    ):
        flex_context["production-price"] = {
            "sensor": (
                production_price_sensor_id if production_price_sensor_id else market_id
            )
        }
    if inflexible_device_sensors or "inflexible-device-sensors" not in flex_context:
        flex_context["inflexible-device-sensors"] = [
            s[0] for s in inflexible_device_sensors
        ]

    capacity_data = {
        "site-power-capacity": capacity_in_mw,
        "site-consumption-capacity": consumption_capacity_in_mw,
        "site-production-capacity": production_capacity_in_mw,
    }
    for key, value in capacity_data.items():
        if value is not None:
            if isinstance(value, (int, float)):
                flex_context[key] = f"{int(value * 1000)} kW"
            else:
                flex_context[key] = value

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


def process_field(value, attributes_data, original_key, new_key, validator):
    if value is not None:
        if isinstance(value, str) and validator(value):
            try:
                attributes_data[original_key] = (
                    ur.Quantity(value).to(ur.Quantity("MW")).magnitude
                )
            except ValueError:
                attributes_data[new_key] = value
        else:
            attributes_data[new_key] = value


def upgrade():
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("flex_context", sa.JSON(), nullable=False, server_default="{}")
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
        inflexible_device_sensors = conn.execute(select_stmt).fetchall()

        # Get fields-to-migrate from attributes
        market_id = attributes_data.get("market_id")
        capacity_in_mw = attributes_data.get("capacity_in_mw") or attributes_data.get(
            "site-power-capacity"
        )
        consumption_capacity_in_mw = attributes_data.get(
            "consumption_capacity_in_mw"
        ) or attributes_data.get("site-consumption-capacity")
        production_capacity_in_mw = attributes_data.get(
            "production_capacity_in_mw"
        ) or attributes_data.get("site-production-capacity")
        ems_peak_consumption_price = attributes_data.get(
            "ems-peak-consumption-price"
        ) or attributes_data.get("site-peak-consumption-price")
        ems_peak_production_price = attributes_data.get(
            "ems-peak-production-price"
        ) or attributes_data.get("site-peak-production-price")
        ems_consumption_breach_price = attributes_data.get(
            "ems-consumption-breach-price"
        ) or attributes_data.get("site-consumption-breach-price")
        ems_production_breach_price = attributes_data.get(
            "ems-production-breach-price"
        ) or attributes_data.get("site-production-breach-price")

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
        if flex_context is None:
            flex_context = {}

        # If possible, fill in the consumption_price_sensor_id and production_price_sensor_id columns
        # (don't bother reverting to the deprecated market_id attribute)
        consumption_price = flex_context.pop("consumption-price", None)
        if (
            isinstance(consumption_price, dict)
            and consumption_price.get("sensor") is not None
        ):
            consumption_price_sensor_id = consumption_price["sensor"]
        else:
            # Unexpected type, so put it back
            if consumption_price is not None:
                flex_context["consumption-price"] = consumption_price
            consumption_price_sensor_id = None
        production_price = flex_context.pop("production-price", None)
        if (
            isinstance(production_price, dict)
            and production_price.get("sensor") is not None
        ):
            production_price_sensor_id = production_price["sensor"]
        else:
            # Unexpected type, so put it back
            if production_price is not None:
                flex_context["production-price"] = production_price
            production_price_sensor_id = None

        site_power_capacity = flex_context.pop("site-power-capacity", None)
        consumption_capacity_in_mw = flex_context.pop("site-consumption-capacity", None)
        production_capacity_in_mw = flex_context.pop("site-production-capacity", None)
        ems_peak_consumption_price = flex_context.pop(
            "site-peak-consumption-price", None
        )
        ems_peak_production_price = flex_context.pop("site-peak-production-price", None)
        ems_consumption_breach_price = flex_context.pop(
            "site-consumption-breach-price", None
        )
        ems_production_breach_price = flex_context.pop(
            "site-production-breach-price", None
        )

        process_field(
            site_power_capacity,
            attributes_data,
            "capacity_in_mw",
            "site-power-capacity",
            is_power_unit,
        )

        process_field(
            consumption_capacity_in_mw,
            attributes_data,
            "consumption_capacity_in_mw",
            "site-consumption-capacity",
            is_power_unit,
        )

        process_field(
            production_capacity_in_mw,
            attributes_data,
            "production_capacity_in_mw",
            "site-production-capacity",
            is_power_unit,
        )

        process_field(
            ems_peak_consumption_price,
            attributes_data,
            "ems-peak-consumption-price",
            "site-peak-consumption-price",
            is_capacity_price_unit,
        )

        process_field(
            ems_peak_production_price,
            attributes_data,
            "ems-peak-production-price",
            "site-peak-production-price",
            is_capacity_price_unit,
        )

        process_field(
            ems_consumption_breach_price,
            attributes_data,
            "ems-consumption-breach-price",
            "site-consumption-breach-price",
            is_capacity_price_unit,
        )

        process_field(
            ems_production_breach_price,
            attributes_data,
            "ems-production-breach-price",
            "site-production-breach-price",
            is_capacity_price_unit,
        )

        inflexible_device_sensors = flex_context.pop("inflexible-device-sensors", [])
        if not isinstance(inflexible_device_sensors, list) or not all(
            isinstance(s, int) for s in inflexible_device_sensors
        ):
            # Unexpected type, so put it back
            flex_context["inflexible-device-sensors"] = inflexible_device_sensors
            inflexible_device_sensors = []

        # Retain data in any new flex-context fields that are not supported after downgrading
        if flex_context:
            attributes_data["flex-context"] = json.dumps(flex_context)

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

        for sensor_id in inflexible_device_sensors:
            insert_stmt = inflexible_sensors_table.insert().values(
                generic_asset_id=asset_id, inflexible_sensor_id=sensor_id
            )
            conn.execute(insert_stmt)

    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.drop_column("flex_context")
