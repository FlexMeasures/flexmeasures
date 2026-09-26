"""Give existing users explicit member rights.

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
    # Imported roles can have explicit IDs while the serial sequence remains at 1.
    # Lock inserts while reconciling it with the largest stored ID. Keep an
    # already-ahead sequence ahead by including its next value.
    connection.execute(sa.text("LOCK TABLE role IN SHARE ROW EXCLUSIVE MODE"))
    max_role_id = connection.execute(sa.text("SELECT MAX(id) FROM role")).scalar_one()
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
    member_role_id = connection.execute(
        sa.text("SELECT id FROM role WHERE name = 'member'")
    ).scalar_one_or_none()
    if member_role_id is None:
        member_role_id = connection.execute(
            sa.text("INSERT INTO role (name) VALUES ('member') RETURNING id")
        ).scalar_one()
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
