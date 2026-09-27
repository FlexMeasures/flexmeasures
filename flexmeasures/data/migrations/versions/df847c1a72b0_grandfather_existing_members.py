"""Seed built-in roles and give existing users explicit member rights.

Revision ID: df847c1a72b0
Revises: c7a2f13b9e04
"""

from alembic import op
import sqlalchemy as sa

revision = "df847c1a72b0"
down_revision = "c7a2f13b9e04"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    roles = (
        ("member", "Operate resources in the home organisation"),
        ("read-only", "Read resources in the home organisation"),
        ("integration", "Read and post data in the home organisation"),
    )
    connection.execute(sa.text("LOCK TABLE role IN SHARE ROW EXCLUSIVE MODE"))
    existing_roles = dict(
        connection.execute(
            sa.text(
                "SELECT name, id FROM role "
                "WHERE name IN ('member', 'read-only', 'integration')"
            )
        ).all()
    )
    missing_roles = [role for role in roles if role[0] not in existing_roles]
    if missing_roles:
        # Imported roles can have explicit IDs while the serial sequence remains at 1.
        # Reconcile it before inserting. Keep an already-ahead sequence ahead.
        max_role_id = connection.execute(
            sa.text("SELECT MAX(id) FROM role")
        ).scalar_one()
        if max_role_id is not None:
            connection.execute(
                sa.text(
                    "SELECT setval("
                    "pg_get_serial_sequence('role', 'id'), "
                    "GREATEST(nextval(pg_get_serial_sequence('role', 'id')), :max_role_id), "
                    "true)"
                ),
                {"max_role_id": max_role_id},
            )
        for name, description in missing_roles:
            existing_roles[name] = connection.execute(
                sa.text(
                    "INSERT INTO role (name, description) "
                    "VALUES (:name, :description) RETURNING id"
                ),
                {"name": name, "description": description},
            ).scalar_one()
    member_role_id = existing_roles["member"]
    # Existing users had implicit home-account rights, even with other roles.
    connection.execute(
        sa.text(
            "INSERT INTO roles_users (user_id, role_id) "
            "SELECT u.id, :member_role_id FROM fm_user AS u "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM roles_users AS ru "
            "WHERE ru.user_id = u.id AND ru.role_id = :member_role_id"
            ")"
        ),
        {"member_role_id": member_role_id},
    )


def downgrade():
    # Do not remove assignments made after this migration.
    pass
