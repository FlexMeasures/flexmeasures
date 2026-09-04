"""add durable automation runs

Revision ID: f3d8e2c9a741
Revises: 84f268f5153c
Create Date: 2026-08-28 13:10:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "f3d8e2c9a741"
down_revision = "84f268f5153c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "automation",
        sa.Column(
            "schedule_revision", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.alter_column("automation", "schedule_revision", server_default=None)

    op.create_table(
        "automation_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("automation_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schedule_revision", sa.Integer(), nullable=False),
        sa.Column("automation_type", sa.String(length=80), nullable=False),
        sa.Column("generator_id", sa.Integer(), nullable=True),
        sa.Column("dispatch_state", sa.String(length=32), nullable=False),
        sa.Column("execution_state", sa.String(length=32), nullable=False),
        sa.Column("claim_owner", sa.String(length=128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("first_enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatch_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_type", sa.String(length=160), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column(
            "parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "dispatch_state IN ('pending', 'claimed', 'partially_queued', 'queued', 'failed')",
            name=op.f("automation_run_automation_run_dispatch_state_ck"),
        ),
        sa.CheckConstraint(
            "execution_state IN ('pending', 'running', 'succeeded', 'failed', 'canceled')",
            name=op.f("automation_run_automation_run_execution_state_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["automation_id"],
            ["automation.id"],
            name=op.f("automation_run_automation_id_automation_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("automation_run_pkey")),
        sa.UniqueConstraint(
            "automation_id",
            "scheduled_at",
            "schedule_revision",
            name="automation_run_occurrence_uq",
        ),
    )
    op.create_index(
        "automation_run_dispatch_state_idx",
        "automation_run",
        ["dispatch_state", "claim_expires_at"],
    )
    op.create_index(
        "automation_run_automation_scheduled_at_idx",
        "automation_run",
        ["automation_id", "scheduled_at"],
    )

    op.create_table(
        "automation_run_attempt",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("owner", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=64), nullable=True),
        sa.Column("queued_job_count", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=160), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["automation_run.id"],
            name=op.f("automation_run_attempt_run_id_automation_run_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("automation_run_attempt_pkey")),
        sa.UniqueConstraint(
            "run_id", "attempt_no", name="automation_run_attempt_no_uq"
        ),
    )

    op.create_table(
        "automation_run_job",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("logical_job_key", sa.String(length=128), nullable=False),
        sa.Column("rq_job_id", sa.String(length=191), nullable=False),
        sa.Column("queue", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_type", sa.String(length=160), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column(
            "depends_on", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'succeeded', 'failed', 'canceled')",
            name=op.f("automation_run_job_automation_run_job_status_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["automation_run.id"],
            name=op.f("automation_run_job_run_id_automation_run_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("automation_run_job_pkey")),
        sa.UniqueConstraint("rq_job_id", name="automation_run_job_rq_job_uq"),
        sa.UniqueConstraint(
            "run_id", "logical_job_key", name="automation_run_job_logical_uq"
        ),
    )
    op.create_index(
        "automation_run_job_run_status_idx",
        "automation_run_job",
        ["run_id", "status"],
    )


def downgrade():
    op.drop_index("automation_run_job_run_status_idx", table_name="automation_run_job")
    op.drop_table("automation_run_job")
    op.drop_table("automation_run_attempt")
    op.drop_index(
        "automation_run_automation_scheduled_at_idx", table_name="automation_run"
    )
    op.drop_index("automation_run_dispatch_state_idx", table_name="automation_run")
    op.drop_table("automation_run")
    op.drop_column("automation", "schedule_revision")
