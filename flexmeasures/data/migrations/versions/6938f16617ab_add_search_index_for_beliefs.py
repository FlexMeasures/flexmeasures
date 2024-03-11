"""add search index for beliefs

Revision ID: 6938f16617ab
Revises: c349f52c700d
Create Date: 2024-03-01 09:55:34.910868

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "6938f16617ab"
down_revision = "c349f52c700d"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("timed_belief", schema=None) as batch_op:
        batch_op.create_index(
            "timed_belief_search_session_idx",
            ["event_start", "sensor_id", "source_id"],
            unique=False,
            postgresql_include=["belief_horizon"],
        )


def downgrade():
    with op.batch_alter_table("timed_belief", schema=None) as batch_op:
        batch_op.drop_index(
            "timed_belief_search_session_idx", postgresql_include=["belief_horizon"]
        )
