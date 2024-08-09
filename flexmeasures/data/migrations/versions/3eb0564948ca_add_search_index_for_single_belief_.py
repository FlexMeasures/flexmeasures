"""add search index for single-belief search

Revision ID: 3eb0564948ca
Revises: 126d65cbe6b4
Create Date: 2024-05-12 15:45:25.337949

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "3eb0564948ca"
down_revision = "126d65cbe6b4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("timed_belief", schema=None) as batch_op:
        batch_op.create_index(
            "timed_belief_search_session_singleevent_idx",
            ["event_start", "sensor_id"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("timed_belief", schema=None) as batch_op:
        batch_op.drop_index("timed_belief_search_session_singleevent_idx")
