"""add warning and error as annotations types

Revision ID: 524800c11eec
Revises: 4b5aa7856932
Create Date: 2024-08-19 15:10:24.323594

"""
from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = "524800c11eec"
down_revision = "4b5aa7856932"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # Check if the 'warning' value exists in the 'annotation_type' enum
    result = conn.execute(
        text(
            """
            SELECT 1
            FROM pg_enum
            WHERE enumlabel = 'warning'
            AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'annotation_type')
        """
        )
    )
    if result.rowcount == 0:
        op.execute("ALTER TYPE annotation_type ADD VALUE 'warning'")

    # Check if the 'error' value exists in the 'annotation_type' enum
    result = conn.execute(
        text(
            """
            SELECT 1
            FROM pg_enum
            WHERE enumlabel = 'error'
            AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'annotation_type')
        """
        )
    )
    if result.rowcount == 0:
        op.execute("ALTER TYPE annotation_type ADD VALUE 'error'")


def downgrade():
    # Enum values cannot be removed in Postgres, so no downgrade action is provided
    pass
