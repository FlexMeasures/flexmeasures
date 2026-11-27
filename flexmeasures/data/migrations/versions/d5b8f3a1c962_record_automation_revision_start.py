"""record when an automation's recurrence revision started

Remember the first minute the current revision of an automation's recurrence is due in,
so that a run waiting for the automation can tell a time from before a reset of its recurrence,
at which it was not due, from a time it was due at but moved past.

An automation still on its first revision started in the minute it was created.
For one on a later revision, the start is not recorded anywhere,
so it is taken to be its first scheduled run of the current revision, or else the minute after its cursor, which a reset puts just before the start.
A new definition also starts a revision, without resetting the recurrence;
for such an automation, this start may come later than the actual one, so a run waiting for it at a time in between goes ahead without it.

Revision ID: d5b8f3a1c962
Revises: c3d9f6a2e481
Create Date: 2026-11-15 23:30:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d5b8f3a1c962"
down_revision = "c3d9f6a2e481"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "automation",
        sa.Column("revision_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("""
        UPDATE automation
        SET revision_started_at = CASE
            WHEN revision = 1 THEN date_trunc('minute', created_at)
            ELSE COALESCE(
                (
                    SELECT min(automation_run.scheduled_at)
                    FROM automation_run
                    WHERE automation_run.automation_id = automation.id
                        AND automation_run.revision = automation.revision
                        AND automation_run.trigger = 'schedule'
                ),
                cursor + interval '1 minute'
            )
        END
        """)
    op.alter_column("automation", "revision_started_at", nullable=False)


def downgrade():
    op.drop_column("automation", "revision_started_at")
