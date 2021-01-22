"""stop using bvp in table names & use singular for table names throughout

Revision ID: 564e8df4e3a9
Revises: 550a9020f1bf
Create Date: 2021-01-12 21:44:43.069141

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "564e8df4e3a9"
down_revision = "550a9020f1bf"
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table("bvp_roles_users", "roles_users")
    op.execute("ALTER SEQUENCE bvp_roles_users_id_seq RENAME TO roles_users_id_seq")

    op.rename_table("bvp_users", "fm_user")
    op.execute("ALTER SEQUENCE bvp_users_id_seq RENAME TO fm_user_id_seq")
    op.execute("ALTER INDEX bvp_users_pkey RENAME TO fm_user_pkey")
    op.execute("ALTER INDEX bvp_users_email_key RENAME TO fm_user_email_key")
    op.execute("ALTER INDEX bvp_users_username_key RENAME TO fm_user_username_key")
    op.execute(
        "ALTER INDEX bvp_users_fs_uniquifier_key RENAME TO fm_user_fs_uniquifier_key"
    )

    op.rename_table("bvp_roles", "role")
    op.execute("ALTER SEQUENCE bvp_roles_id_seq RENAME TO role_id_seq")
    op.execute("ALTER INDEX bvp_roles_pkey RENAME TO role_pkey")
    op.execute("ALTER INDEX bvp_roles_name_key RENAME TO role_name_key")

    op.rename_table("data_sources", "data_source")
    op.execute("ALTER SEQUENCE data_sources_id_seq RENAME TO data_source_id_seq")
    op.execute("ALTER INDEX data_sources_user_id_key RENAME TO data_source_user_id_key")


def downgrade():
    op.rename_table("roles_users", "bvp_users")
    op.execute("ALTER SEQUENCE roles_users_id_seq RENAME TO bvp_roles_users_id_seq")

    op.rename_table("fm_user", "bvp_users")
    op.execute("ALTER SEQUENCE fm_user_id_seq RENAME TO bvp_users_id_seq")
    op.execute("ALTER INDEX fm_user_pkey RENAME TO bvp_users_pkey")
    op.execute("ALTER INDEX fm_user_email_key RENAME TO bvp_users_email_key")
    op.execute("ALTER INDEX fm_user_username_key RENAME TO bvp_users_username_key")
    op.execute(
        "ALTER INDEX fm_user_fs_uniquifier_key RENAME TO bvp_users_fs_uniquifier_key"
    )

    op.rename_table("role", "bvp_roles")
    op.execute("ALTER SEQUENCE role_id_seq RENAME TO bvp_roles_id_seq")
    op.execute("ALTER INDEX role_pkey RENAME TO bvp_roles_pkey")
    op.execute("ALTER INDEX role_name_key RENAME TO bvp_roles_name_key")

    op.rename_table("data_source", "data_sources")
    op.execute("ALTER SEQUENCE data_source_id_seq RENAME TO data_sources_id_seq")
    op.execute("ALTER INDEX data_source_user_id_key RENAME TO data_sources_user_id_key")
