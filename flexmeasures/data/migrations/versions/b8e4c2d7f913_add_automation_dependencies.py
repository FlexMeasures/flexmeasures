"""add automation dependencies

Let an automation's runs wait for the run of another automation at the same scheduled time.
A run that waits is 'waiting' to be dispatched, and a run whose upstream run failed is 'skipped'.

Revision ID: b8e4c2d7f913
Revises: f7c2e8b1a409
Create Date: 2026-10-14 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b8e4c2d7f913"
down_revision = "f7c2e8b1a409"
branch_labels = None
depends_on = None

DISPATCH_STATE_CK = "automation_run_automation_run_dispatch_state_ck"
EXECUTION_STATE_CK = "automation_run_automation_run_execution_state_ck"


def upgrade():
    op.create_table(
        "automation_dependency",
        sa.Column("automation_id", sa.Integer(), nullable=False),
        sa.Column("upstream_id", sa.Integer(), nullable=False),
        sa.Column(
            "allow_failure",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.ForeignKeyConstraint(
            ["automation_id"],
            ["automation.id"],
            name=op.f("automation_dependency_automation_id_automation_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["upstream_id"],
            ["automation.id"],
            name=op.f("automation_dependency_upstream_id_automation_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "automation_id", "upstream_id", name=op.f("automation_dependency_pkey")
        ),
    )
    op.alter_column("automation_dependency", "allow_failure", server_default=None)
    op.create_index(
        op.f("automation_dependency_upstream_id_idx"),
        "automation_dependency",
        ["upstream_id"],
    )

    op.drop_constraint(op.f(DISPATCH_STATE_CK), "automation_run", type_="check")
    op.create_check_constraint(
        op.f(DISPATCH_STATE_CK),
        "automation_run",
        "dispatch_state IN ('pending', 'claimed', 'waiting', 'partially_queued', 'queued', 'failed')",
    )
    op.drop_constraint(op.f(EXECUTION_STATE_CK), "automation_run", type_="check")
    op.create_check_constraint(
        op.f(EXECUTION_STATE_CK),
        "automation_run",
        "execution_state IN ('pending', 'running', 'succeeded', 'failed', 'canceled', 'skipped')",
    )


def downgrade():
    # The narrower constraints below would refuse these runs, so give them the states they had before a run could wait.
    # A waiting run was claimed and never queued anything, and a skipped run never ran.
    op.execute(
        "UPDATE automation_run SET dispatch_state = 'failed' WHERE dispatch_state = 'waiting'"
    )
    op.execute(
        "UPDATE automation_run SET execution_state = 'canceled' WHERE execution_state = 'skipped'"
    )
    op.drop_constraint(op.f(EXECUTION_STATE_CK), "automation_run", type_="check")
    op.create_check_constraint(
        op.f(EXECUTION_STATE_CK),
        "automation_run",
        "execution_state IN ('pending', 'running', 'succeeded', 'failed', 'canceled')",
    )
    op.drop_constraint(op.f(DISPATCH_STATE_CK), "automation_run", type_="check")
    op.create_check_constraint(
        op.f(DISPATCH_STATE_CK),
        "automation_run",
        "dispatch_state IN ('pending', 'claimed', 'partially_queued', 'queued', 'failed')",
    )
    op.drop_index(
        op.f("automation_dependency_upstream_id_idx"),
        table_name="automation_dependency",
    )
    op.drop_table("automation_dependency")
