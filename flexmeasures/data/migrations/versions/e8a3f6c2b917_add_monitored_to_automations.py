"""Let an automation opt out of monitoring

Revision ID: e8a3f6c2b917
Revises: d4b7e9a1c362
Create Date: 2026-10-12 10:00:00.000000

`flexmeasures monitor automations` skips the runs of an automation whose ``monitored`` is false.
Every existing automation stays monitored.
``monitoring_resumed_at`` records when monitoring was last switched back on,
so that the digest can tell which of the runs it reports failed while the automation was not monitored.
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
    op.add_column(
        "automation",
        sa.Column("monitoring_resumed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("automation", "monitoring_resumed_at")
    op.drop_column("automation", "monitored")
