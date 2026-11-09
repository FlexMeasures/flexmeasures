"""Flag automations as critical, and record when their failure was handed to the hooks.

Revision ID: d4a17c6b3e92
Revises: bf22b21d0990
"""

from alembic import op
import sqlalchemy as sa

revision = "d4a17c6b3e92"
down_revision = "bf22b21d0990"
branch_labels = None
depends_on = None


def upgrade():
    # Existing automations are not critical: flagging one is a deliberate act.
    with op.batch_alter_table("automation") as batch_op:
        batch_op.add_column(
            sa.Column(
                "critical",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    # Runs from before this migration are never notified about retroactively.
    with op.batch_alter_table("automation_run") as batch_op:
        batch_op.add_column(
            sa.Column(
                "critical_failure_notified_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )


def downgrade():
    with op.batch_alter_table("automation_run") as batch_op:
        batch_op.drop_column("critical_failure_notified_at")
    with op.batch_alter_table("automation") as batch_op:
        batch_op.drop_column("critical")
