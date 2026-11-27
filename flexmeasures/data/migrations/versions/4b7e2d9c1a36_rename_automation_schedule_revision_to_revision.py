"""Rename automation schedule_revision to revision

An automation's revision now also counts edits to what it computes, not only to its schedule.

Revision ID: 4b7e2d9c1a36
Revises: bf22b21d0990
Create Date: 2026-10-30 12:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "4b7e2d9c1a36"
down_revision = "bf22b21d0990"
branch_labels = None
depends_on = None


def upgrade():
    # Renaming a column keeps the unique constraint on automation_run, which follows the column.
    op.alter_column("automation", "schedule_revision", new_column_name="revision")
    op.alter_column("automation_run", "schedule_revision", new_column_name="revision")


def downgrade():
    op.alter_column("automation_run", "revision", new_column_name="schedule_revision")
    op.alter_column("automation", "revision", new_column_name="schedule_revision")
