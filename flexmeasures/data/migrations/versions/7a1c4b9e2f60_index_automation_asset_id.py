"""index automation asset_id

Revision ID: 7a1c4b9e2f60
Revises: 9f2b6e1d4a73
Create Date: 2026-09-01 12:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "7a1c4b9e2f60"
down_revision = "9f2b6e1d4a73"
branch_labels = None
depends_on = None


def upgrade():
    # PostgreSQL does not index a foreign key by itself, and automations are looked up by asset
    # (on an asset's automations page, and when finding the automations that feed a sensor).
    op.create_index(
        op.f("ix_automation_asset_id"), "automation", ["asset_id"], unique=False
    )


def downgrade():
    op.drop_index(op.f("ix_automation_asset_id"), table_name="automation")
