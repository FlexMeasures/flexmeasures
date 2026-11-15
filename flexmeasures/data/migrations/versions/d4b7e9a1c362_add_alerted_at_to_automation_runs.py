"""Record when an automation run was reported by `flexmeasures monitor automations`

Revision ID: d4b7e9a1c362
Revises: bf22b21d0990
Create Date: 2026-10-07 10:00:00.000000

The monitor reports each failed or stuck run once, and marks it in ``alerted_at``.
The upgrade marks the runs that had already failed for good as reported, so that the first monitoring run does not report every failure on record.
It judges them by the monitor's rules as they stand at this revision, with the default stuck threshold of 6 hours,
and leaves out any run that may still be retried or finish.

The partial index holds only the runs the monitor has to look at:
those not reported yet which failed, are still running, or never finished their dispatch.
Every other run, which is nearly all of them, stays out of it.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d4b7e9a1c362"
down_revision = "bf22b21d0990"
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
    # Copied from the monitor's query rather than imported, so this migration keeps doing what it did when the query changes.
    op.execute("""
        UPDATE automation_run
        SET alerted_at = now()
        WHERE execution_state = 'failed'
           OR (execution_state = 'running' AND execution_started_at <= now() - interval '6 hours')
           OR (
               dispatch_completed_at IS NULL
               AND (claim_owner IS NULL OR claim_expires_at IS NULL OR claim_expires_at <= now())
               AND NOT (automation_type = 'forecasting' AND attempt_count < 5)
           )
        """)


def downgrade():
    op.drop_index("automation_run_unalerted_idx", table_name="automation_run")
    op.drop_column("automation_run", "alerted_at")
