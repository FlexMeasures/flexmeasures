"""Added flexmodel to generic asset model

Revision ID: f0ee99278f6f
Revises: cb8df44ebda5
Create Date: 2025-04-15 11:00:13.154048

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f0ee99278f6f"
down_revision = "cb8df44ebda5"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###

    # Add the new column
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("flex_model", sa.JSON(), nullable=False, server_default="{}")
        )

    sensor_table = sa.Table(
        "sensor",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("attributes", sa.JSON),
        sa.Column("generic_asset_id", sa.Integer),
    )

    generic_asset_table = sa.Table(
        "generic_asset",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("flex_model", sa.JSON),
    )

    # Fetch all sensors
    conn = op.get_bind()
    result = conn.execute(
        sa.select(
            sensor_table.c.id,
            sensor_table.c.attributes,
            sensor_table.c.generic_asset_id,
        )
    )
    sensors = result.fetchall()

    # Group relevant sensors by generic_asset_id
    from collections import defaultdict

    grouped = defaultdict(list)

    for sensor in sensors:
        attributes = sensor.attributes or {}
        if "soc-min" in attributes:
            grouped[sensor.generic_asset_id].append(sensor)

    # Process each group
    for asset_id, sensors_with_key in grouped.items():
        if len(sensors_with_key) > 1:
            raise Exception(
                f"Multiple sensors with 'soc-min' found for asset_id {asset_id}: {[s.id for s in sensors_with_key]}"
            )

        sensor = sensors_with_key[0]
        if sensor.attributes.get("soc-min") is not None:
            # check if value is a int or float
            if not isinstance(sensor.attributes.get("soc-min"), (int, float)):
                raise Exception(
                    f"Invalid value for 'soc-min' in sensor {sensor.id}: {sensor.attributes['soc-min']}"
                )
            soc_min_value_kwh = sensor.attributes.get("soc-min") * 1000
            soc_min_in_kwh = f"{soc_min_value_kwh} kWh"
            flex_model_data = {"soc-min": soc_min_in_kwh}

            stmt = (
                generic_asset_table.update()
                .where(generic_asset_table.c.id == asset_id)
                .values(flex_model=flex_model_data)
            )

            conn.execute(stmt)

            # Update the sensor attributes to remove 'soc-min'
            sensor.attributes.pop("soc-min", None)
            stmt = (
                sensor_table.update()
                .where(sensor_table.c.id == sensor.id)
                .values(attributes=sensor.attributes)
            )
            conn.execute(stmt)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.drop_column("flex_model")

    # ### end Alembic commands ###
