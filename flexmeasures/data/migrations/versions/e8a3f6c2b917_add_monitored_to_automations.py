"""Let an automation opt out of monitoring

Revision ID: e8a3f6c2b917
Revises: d4b7e9a1c362
Create Date: 2026-10-12 10:00:00.000000

`flexmeasures monitor automations` skips the runs of an automation whose ``monitored`` is false.
Every existing automation stays monitored.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e8a3f6c2b917"
down_revision = "d4b7e9a1c362"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "automation",
        sa.Column(
            "monitored", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )


def downgrade():
    op.drop_column("automation", "monitored")
