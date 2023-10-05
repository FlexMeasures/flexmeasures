"""Drop generic_asset_name_account_id_key constraint

Revision ID: ac5e340cccea
Revises: 40d6c8e4be94
Create Date: 2023-10-05 15:13:36.641051

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "ac5e340cccea"
down_revision = "40d6c8e4be94"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        "generic_asset_name_account_id_key", "generic_asset", type_="unique"
    )


def downgrade():
    op.create_unique_constraint(
        "generic_asset_name_account_id_key", "generic_asset", ["name", "account_id"]
    )
