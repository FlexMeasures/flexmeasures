"""better order in index for single most recent event

Revision ID: b8f3cda5e023
Revises: b526da466b74
Create Date: 2025-07-30 12:28:03.489985

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "b8f3cda5e023"
down_revision = "b526da466b74"
branch_labels = None
depends_on = None


def upgrade():
    """
    Re-create the index with correct order
    """
    with op.batch_alter_table("timed_belief", schema=None) as batch_op:
        batch_op.drop_index("timed_belief_search_session_singleevent_idx")
    with op.batch_alter_table("timed_belief", schema=None) as batch_op:
        batch_op.create_index(
            "timed_belief_search_session_singleevent_idx",
            ["sensor_id", "event_start"],
            unique=False,
        )


def downgrade():
    """
    Re-create the original index
    """
    with op.batch_alter_table("timed_belief", schema=None) as batch_op:
        batch_op.drop_index("timed_belief_search_session_singleevent_idx")
    with op.batch_alter_table("timed_belief", schema=None) as batch_op:
        batch_op.create_index(
            "timed_belief_search_session_singleevent_idx",
            ["event_start", "sensor_id"],
            unique=False,
        )
