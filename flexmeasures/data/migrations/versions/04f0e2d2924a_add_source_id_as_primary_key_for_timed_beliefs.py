"""add source id as primary key for timed beliefs

Revision ID: 04f0e2d2924a
Revises: e62ac5f519d7
Create Date: 2021-04-10 13:53:22.561718

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "04f0e2d2924a"
down_revision = "e62ac5f519d7"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("timed_belief_pkey", "timed_belief")
    op.create_primary_key(
        "timed_belief_pkey",
        "timed_belief",
        [
            "event_start",
            "belief_horizon",
            "cumulative_probability",
            "sensor_id",
            "source_id",
        ],
    )


def downgrade():
    op.drop_constraint("timed_belief_pkey", "timed_belief")
    op.create_primary_key(
        "timed_belief_pkey",
        "timed_belief",
        ["event_start", "belief_horizon", "cumulative_probability", "sensor_id"],
    )
