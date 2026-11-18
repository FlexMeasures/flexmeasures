"""Drop plan.rate_limit_key, as triggers are now always counted per account

Revision ID: 29d0c9ae8504
Revises: c5e1a7b94d20
Create Date: 2026-10-07 12:00:00.000000

Plans could choose to count triggers per account, per account and asset, or per user.
Only per account is left, so the column and its enum type go.
A downgrade restores both, but cannot restore what the column held, so every plan falls back to the server-wide setting again.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "29d0c9ae8504"
down_revision = "c5e1a7b94d20"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("plan", schema=None) as batch_op:
        batch_op.drop_column("rate_limit_key")
    sa.Enum(name="ratelimitkey").drop(op.get_bind(), checkfirst=True)


def downgrade():
    rate_limit_key = sa.Enum(
        "ACCOUNT_PLUS_ASSET", "ACCOUNT", "USER", name="ratelimitkey"
    )
    rate_limit_key.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("plan", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rate_limit_key", rate_limit_key, nullable=True))
