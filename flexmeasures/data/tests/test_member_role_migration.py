"""Regression checks for the built-in role data migration."""

import importlib

from sqlalchemy import text


def test_migration_repairs_stale_role_id_sequence(fresh_db, monkeypatch):
    """Imported role IDs must not collide with the next generated ID."""
    connection = fresh_db.session.connection()
    connection.execute(
        text("INSERT INTO role (id, name) VALUES (1, 'admin'), (7, 'consultant')")
    )
    connection.execute(
        text("SELECT setval(pg_get_serial_sequence('role', 'id'), 1, false)")
    )
    migration = importlib.import_module(
        "flexmeasures.data.migrations.versions."
        "df847c1a72b0_grandfather_existing_members"
    )
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

    migration.upgrade()

    assert (
        connection.execute(
            text("SELECT id FROM role WHERE name = 'member'")
        ).scalar_one()
        == 8
    )
    assert connection.execute(
        text("SELECT name FROM role WHERE id IN (8, 9, 10) ORDER BY id")
    ).scalars().all() == ["member", "read-only", "integration"]
    assert (
        connection.execute(
            text("INSERT INTO role (name) VALUES ('next-role') RETURNING id")
        ).scalar_one()
        == 11
    )


def test_role_migration_preserves_existing_roles_and_is_idempotent(
    fresh_db, monkeypatch
):
    """Existing roles and imported IDs survive the combined migration."""
    connection = fresh_db.session.connection()
    connection.execute(
        text(
            "INSERT INTO role (id, name, description) VALUES "
            "(1, 'admin', NULL), (7, 'consultant', NULL), "
            "(8, 'read-only', 'Custom description')"
        )
    )
    connection.execute(
        text("SELECT setval(pg_get_serial_sequence('role', 'id'), 1, false)")
    )
    migration = importlib.import_module(
        "flexmeasures.data.migrations.versions."
        "df847c1a72b0_grandfather_existing_members"
    )
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

    migration.upgrade()
    migration.upgrade()

    rows = connection.execute(
        text("SELECT name, description FROM role ORDER BY id")
    ).all()
    assert [name for name, _ in rows] == [
        "admin",
        "consultant",
        "read-only",
        "member",
        "integration",
    ]
    assert rows[2].description == "Custom description"
    assert (
        connection.execute(
            text("INSERT INTO role (name) VALUES ('next-role') RETURNING id")
        ).scalar_one()
        == 11
    )
