"""add warning and error as annotations types

Revision ID: 524800c11eec
Revises: 4b5aa7856932
Create Date: 2024-08-19 15:10:24.323594

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "524800c11eec"
down_revision = "4b5aa7856932"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE annotation_type ADD VALUE 'warning'")
    op.execute("ALTER TYPE annotation_type ADD VALUE 'error'")


def downgrade():
    # Enum values cannot be removed in Postgres, so no downgrade action is provided
    pass
