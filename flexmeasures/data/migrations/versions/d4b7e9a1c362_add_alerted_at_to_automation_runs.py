"""Record when an automation run was reported by `flexmeasures monitor automations`

Revision ID: d4b7e9a1c362
Revises: c5e1a7b94d20
Create Date: 2026-10-07 10:00:00.000000

The monitor reports each failed or stuck run once, and marks it in ``alerted_at``.
Every run recorded before this upgrade has no mark, so the first monitoring run reports the failures already on record, collapsed per automation.

The partial index holds only the runs the monitor has to look at:
those not reported yet which failed, are still running, or never finished their dispatch.
Every other run, which is nearly all of them, stays out of it.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d4b7e9a1c362"
down_revision = "c5e1a7b94d20"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "automation_run",
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "automation_run_unalerted_idx",
        "automation_run",
        ["automation_id"],
        postgresql_where=sa.text(
            "alerted_at IS NULL"
            " AND (execution_state = 'failed' OR execution_state = 'running' OR dispatch_completed_at IS NULL)"
        ),
    )


def downgrade():
    op.drop_index("automation_run_unalerted_idx", table_name="automation_run")
    op.drop_column("automation_run", "alerted_at")
