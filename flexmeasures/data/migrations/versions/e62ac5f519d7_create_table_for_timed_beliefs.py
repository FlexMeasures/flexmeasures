"""create table for timed beliefs

Revision ID: e62ac5f519d7
Revises: a528c3c81506
Create Date: 2021-03-28 16:26:45.025994

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e62ac5f519d7"
down_revision = "a528c3c81506"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "timed_belief",
        sa.Column(
            "event_start", sa.DateTime(timezone=True), nullable=False, index=True
        ),
        sa.Column("belief_horizon", sa.Interval(), nullable=False),
        sa.Column("cumulative_probability", sa.Float(), nullable=False, default=0.5),
        sa.Column("event_value", sa.Float(), nullable=False),
        sa.Column("sensor_id", sa.Integer(), nullable=False, index=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["sensor_id"],
            ["sensor.id"],
            name=op.f("timed_belief_sensor_id_sensor_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_source.id"],
            name=op.f("timed_belief_source_id_source_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "event_start",
            "belief_horizon",
            "cumulative_probability",
            "sensor_id",
            name=op.f("timed_belief_pkey"),
        ),
    )


def downgrade():
    op.drop_table("timed_belief")
