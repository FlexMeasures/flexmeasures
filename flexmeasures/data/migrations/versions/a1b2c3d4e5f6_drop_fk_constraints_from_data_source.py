"""Drop FK constraints from data_source for data lineage preservation

When users or accounts are deleted, we want to preserve the historical
user_id and account_id values in data_source rows for lineage purposes,
rather than cascade-deleting or nullifying them.

Revision ID: a1b2c3d4e5f6
Revises: 9877450113f6
Create Date: 2026-03-25 00:00:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "9877450113f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.drop_constraint(
            op.f("data_source_account_id_account_fkey"), type_="foreignkey"
        )
        batch_op.drop_constraint("data_sources_user_id_fkey", type_="foreignkey")


def downgrade():
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "data_sources_user_id_fkey",
            "fm_user",
            ["user_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            op.f("data_source_account_id_account_fkey"),
            "account",
            ["account_id"],
            ["id"],
        )
