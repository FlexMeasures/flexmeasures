"""Drop FK constraints from data_source for data lineage preservation

When users or accounts are deleted, we want to preserve the historical
user_id and account_id values in data_source rows for lineage purposes,
rather than cascade-deleting or nullifying them.

Revision ID: a1b2c3d4e5f6
Revises: 9877450113f6
Create Date: 2026-03-25 00:00:00.000000

"""

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "9877450113f6"
branch_labels = None
depends_on = None


def upgrade():
    # Inspect existing FK constraints to handle different database states gracefully
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_fks = inspector.get_foreign_keys("data_source")
    existing_fk_names = [fk["name"] for fk in existing_fks]

    with op.batch_alter_table("data_source", schema=None) as batch_op:
        # Drop the account_id FK if it exists
        if "data_source_account_id_account_fkey" in existing_fk_names:
            batch_op.drop_constraint(
                "data_source_account_id_account_fkey", type_="foreignkey"
            )

        # Drop the user_id FK if it exists (may have auto-generated name)
        for fk_name in existing_fk_names:
            if "user_id" in fk_name:
                batch_op.drop_constraint(fk_name, type_="foreignkey")
                break


def downgrade():
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "data_source_user_id_fkey",
            "fm_user",
            ["user_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "data_source_account_id_account_fkey",
            "account",
            ["account_id"],
            ["id"],
        )
