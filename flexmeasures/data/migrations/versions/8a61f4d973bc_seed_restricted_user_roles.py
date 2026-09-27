"""Seed restricted user roles for existing installations.

Revision ID: 8a61f4d973bc
Revises: df847c1a72b0
"""

from alembic import op
import sqlalchemy as sa

revision = "8a61f4d973bc"
down_revision = "df847c1a72b0"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    roles = (
        ("read-only", "Read resources in the home organisation"),
        ("integration", "Read and post data in the home organisation"),
    )
    existing = set(
        connection.execute(
            sa.text("SELECT name FROM role WHERE name IN ('read-only', 'integration')")
        ).scalars()
    )
    missing = [
        (name, description) for name, description in roles if name not in existing
    ]
    if not missing:
        return
    # Existing installations may have imported explicit role IDs.
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
    for name, description in missing:
        connection.execute(
            sa.text(
                "INSERT INTO role (name, description) "
                "VALUES (:name, :description) ON CONFLICT (name) DO NOTHING"
            ),
            {"name": name, "description": description},
        )


def downgrade():
    # Keep roles that may have been assigned after this migration.
    pass
