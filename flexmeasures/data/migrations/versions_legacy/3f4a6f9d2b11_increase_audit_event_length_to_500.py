"""increase_audit_event_length_to_500

Revision ID: 3f4a6f9d2b11
Revises: 8b62f8129f34
Create Date: 2026-03-31

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3f4a6f9d2b11"
down_revision = "8b62f8129f34"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "audit_log",
        "event",
        existing_type=sa.String(length=255),
        type_=sa.String(length=500),
        existing_nullable=True,
    )
    op.alter_column(
        "asset_audit_log",
        "event",
        existing_type=sa.String(length=255),
        type_=sa.String(length=500),
        existing_nullable=True,
    )


def downgrade():
    op.alter_column(
        "asset_audit_log",
        "event",
        existing_type=sa.String(length=500),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "audit_log",
        "event",
        existing_type=sa.String(length=500),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
