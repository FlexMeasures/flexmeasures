"""delete asset if sensor is deleted

Revision ID: 30f7b63069e1
Revises: 038bab973c40
Create Date: 2022-03-18 14:44:56.718765

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "30f7b63069e1"
down_revision = "038bab973c40"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("asset_id_sensor_fkey", "asset", type_="foreignkey")
    op.create_foreign_key(
        op.f("asset_id_sensor_fkey"),
        "asset",
        "sensor",
        ["id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade():
    op.drop_constraint(op.f("asset_id_sensor_fkey"), "asset", type_="foreignkey")
    op.create_foreign_key("asset_id_sensor_fkey", "asset", "sensor", ["id"], ["id"])
