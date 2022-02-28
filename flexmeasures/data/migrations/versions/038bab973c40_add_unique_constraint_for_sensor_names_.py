"""
- add unique constraint for sensor names within a generic asset (on Sensor.name & Sensor.generic_asset_id)
- in existing sensor, rename wind_speed to "wind speed" and "radiation" to "irradiance"

Revision ID: 038bab973c40
Revises: 7f8b8920355f
Create Date: 2022-02-16 22:35:26.330950

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "038bab973c40"
down_revision = "7f8b8920355f"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_unique_constraint(
        "sensor_name_generic_asset_id_key", "sensor", ["name", "generic_asset_id"]
    )
    # ### end Alembic commands ###
    op.execute(
        """
        update sensor set name = 'wind speed' where name = 'wind_speed';
        update sensor set name = 'irradiance' where name = 'radiation';
        """
    )


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint("sensor_name_generic_asset_id_key", "sensor", type_="unique")
    # ### end Alembic commands ###
    op.execute(
        """
        update sensor set name = 'wind_speed' where name = 'wind speed';
        update sensor set name = 'radiation' where name = 'irradiance';
        """
    )
