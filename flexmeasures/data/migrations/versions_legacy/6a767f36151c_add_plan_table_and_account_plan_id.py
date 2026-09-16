"""add plan table and account.plan_id

Revision ID: 6a767f36151c
Revises: 4b0f2e9c1a6d
Create Date: 2026-07-13 16:39:05.655364

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "6a767f36151c"
down_revision = "4b0f2e9c1a6d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("default_rate_limit", sa.String(length=80), nullable=True),
        sa.Column("trigger_rate_limit", sa.String(length=80), nullable=True),
        sa.Column(
            "rate_limit_key",
            sa.Enum("ACCOUNT_PLUS_ASSET", "ACCOUNT", "USER", name="ratelimitkey"),
            nullable=True,
        ),
        sa.Column("max_users", sa.Integer(), nullable=True),
        sa.Column("max_assets", sa.Integer(), nullable=True),
        sa.Column("max_clients", sa.Integer(), nullable=True),
        sa.Column(
            "legacy", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("plan_pkey")),
        sa.UniqueConstraint("name", name=op.f("plan_name_key")),
    )
    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.add_column(sa.Column("plan_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("account_plan_id_plan_fkey"), "plan", ["plan_id"], ["id"]
        )


def downgrade():
    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("account_plan_id_plan_fkey"), type_="foreignkey"
        )
        batch_op.drop_column("plan_id")

    op.drop_table("plan")
    sa.Enum(name="ratelimitkey").drop(op.get_bind(), checkfirst=True)
