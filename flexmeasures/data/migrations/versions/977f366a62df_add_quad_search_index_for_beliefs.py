"""add quad-search index for beliefs

Revision ID: 977f366a62df
Revises: c349f52c700d
Create Date: 2024-02-28 14:08:47.362662

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "977f366a62df"
down_revision = "c349f52c700d"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("timed_belief", schema=None) as batch_op:
        batch_op.create_index(
            "timed_belief_quad_search_idx",
            ["event_start", "source_id", "sensor_id", "belief_horizon"],
        )


def downgrade():
    with op.batch_alter_table("timed_belief", schema=None) as batch_op:
        batch_op.drop_index("timed_belief_quad_search_idx")
