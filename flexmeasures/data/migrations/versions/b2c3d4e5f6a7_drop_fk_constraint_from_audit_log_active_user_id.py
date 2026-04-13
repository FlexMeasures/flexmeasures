"""Drop FK constraint from audit_log.active_user_id for data lineage preservation

When users are deleted, we want to preserve the historical active_user_id
values in audit_log rows for lineage purposes, rather than cascade-deleting
or nullifying them.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-27 00:00:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "9877450113f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_constraint(
            op.f("audit_log_active_user_id_fm_user_fkey"), type_="foreignkey"
        )
        batch_op.drop_constraint(
            op.f("audit_log_affected_user_id_fm_user_fkey"), type_="foreignkey"
        )
        batch_op.drop_constraint(
            op.f("audit_log_affected_account_id_account_fkey"), type_="foreignkey"
        )


def downgrade():
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.create_foreign_key(
            op.f("audit_log_affected_account_id_account_fkey"),
            "account",
            ["affected_account_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            op.f("audit_log_affected_user_id_fm_user_fkey"),
            "fm_user",
            ["affected_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            op.f("audit_log_active_user_id_fm_user_fkey"),
            "fm_user",
            ["active_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
