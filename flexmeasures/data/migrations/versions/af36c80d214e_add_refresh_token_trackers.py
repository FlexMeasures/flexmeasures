"""Add refresh-token family tracking.

Revision ID: af36c80d214e
Revises: bf22b21d0990
"""

from alembic import op
import sqlalchemy as sa

revision = "af36c80d214e"
down_revision = "bf22b21d0990"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "refresh_token_tracker",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("fm_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("refresh_family", sa.String(64), nullable=False, unique=True),
        sa.Column("gen", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime()),
        sa.Column(
            "create_datetime",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_refresh_token_tracker_user_id", "refresh_token_tracker", ["user_id"]
    )


def downgrade():
    op.drop_table("refresh_token_tracker")
