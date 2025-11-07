"""add generic_asset.external_id

Revision ID: 6cca6c002135
Revises: d914c764fcb7
Create Date: 2025-10-27 16:43:25.272665

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "6cca6c002135"
down_revision = "d914c764fcb7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("external_id", sa.String(length=80), nullable=True)
        )
        batch_op.create_unique_constraint(
            "generic_asset_account_id_external_id_key", ["account_id", "external_id"]
        )


def downgrade():
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.drop_constraint(
            "generic_asset_account_id_external_id_key", type_="unique"
        )
        batch_op.drop_column("external_id")
