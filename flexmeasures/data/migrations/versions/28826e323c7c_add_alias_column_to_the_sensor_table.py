"""Add alias column to the sensor table

Revision ID: 28826e323c7c
Revises: 5a9473a817cb
Create Date: 2023-11-09 13:16:03.043965

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "28826e323c7c"
down_revision = "5a9473a817cb"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sensor",
        sa.Column(
            "alias",
            sa.VARCHAR(120),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        op.f("sensor_alias_generic_asset_id"),
        "sensor",
        ["alias", "generic_asset_id"],
    )


def downgrade():
    connection = op.get_bind()
    number_sensors_with_alias = connection.execute(
        "SELECT COUNT(*) from sensor WHERE alias is not null;"
    ).fetchone()[0]

    print(
        f"Dropping column `alias` from the table `sensor`. Currently, the database contains {number_sensors_with_alias} sensor/s that have an alias defined, beware that this information will be gone."
    )
    op.drop_constraint("sensor_alias_generic_asset_id", "sensor", type_="unique")
    op.drop_column("sensor", "alias")
