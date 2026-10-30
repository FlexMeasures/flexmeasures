"""record on-demand automation runs

Say whether an automation run was due by its schedule or asked for on demand,
so that a chain of automations run on demand can wait for each other's runs, too.
Only one run per scheduled occurrence is allowed, as before, while on-demand runs can share a time with any other run.

Revision ID: c3d9f6a2e481
Revises: b8e4c2d7f913
Create Date: 2026-10-30 03:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3d9f6a2e481"
down_revision = "b8e4c2d7f913"
branch_labels = None
depends_on = None

TRIGGER_CK = "automation_run_automation_run_trigger_ck"


def upgrade():
    op.add_column(
        "automation_run",
        sa.Column(
            "trigger",
            sa.String(16),
            nullable=False,
            server_default="schedule",
        ),
    )
    op.alter_column("automation_run", "trigger", server_default=None)
    op.create_check_constraint(
        op.f(TRIGGER_CK),
        "automation_run",
        "trigger IN ('schedule', 'on-demand')",
    )
    op.drop_constraint("automation_run_occurrence_uq", "automation_run", type_="unique")
    op.create_index(
        "automation_run_occurrence_uq",
        "automation_run",
        ["automation_id", "scheduled_at", "schedule_revision"],
        unique=True,
        postgresql_where=sa.text("trigger = 'schedule'"),
    )


def downgrade():
    # Without the trigger, on-demand runs could clash with scheduled runs at the same time, so they go.
    op.execute("DELETE FROM automation_run WHERE trigger = 'on-demand'")
    op.drop_index("automation_run_occurrence_uq", table_name="automation_run")
    op.create_unique_constraint(
        "automation_run_occurrence_uq",
        "automation_run",
        ["automation_id", "scheduled_at", "schedule_revision"],
    )
    op.drop_constraint(op.f(TRIGGER_CK), "automation_run", type_="check")
    op.drop_column("automation_run", "trigger")
