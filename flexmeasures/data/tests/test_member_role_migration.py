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
            text("SELECT id FROM role WHERE name = 'account-member'")
        ).scalar_one()
        == 8
    )
    assert connection.execute(
        text("SELECT name FROM role WHERE id IN (8, 9, 10) ORDER BY id")
    ).scalars().all() == [
        "account-member",
        "account-reader",
        "account-data-integrator",
    ]
    assert (
        connection.execute(
            text("SELECT description FROM role WHERE name = 'admin'")
        ).scalar_one()
        == "Full access across all organisations"
    )
    assert (
        connection.execute(
            text("SELECT description FROM role WHERE name = 'consultant'")
        ).scalar_one()
        == "Manage client organisations through consultancy access"
    )
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
            "(1, 'admin', NULL), (2, 'Prosumer', 'Custom role'), "
            "(7, 'consultant', 'User can see client accounts'), "
            "(8, 'account-reader', 'Old built-in description')"
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
        "Prosumer",
        "consultant",
        "account-reader",
        "account-member",
        "account-data-integrator",
    ]
    descriptions = {name: description for name, description in rows}
    assert descriptions["Prosumer"] == "Custom role"
    assert descriptions["consultant"] == (
        "Manage client organisations through consultancy access"
    )
    assert descriptions["account-reader"] == "Read home organisation resources"
    assert descriptions["account-member"] == (
        "Read and operate home organisation resources"
    )
    assert descriptions["account-data-integrator"] == (
        "Read and post home organisation data; reset own password"
    )
    assert (
        connection.execute(
            text("INSERT INTO role (name) VALUES ('next-role') RETURNING id")
        ).scalar_one()
        == 11
    )


def test_role_migration_assigns_account_member_to_existing_users(
    fresh_db, setup_roles_users_fresh_db, monkeypatch
):
    """All existing users receive the final account-member role."""
    connection = fresh_db.session.connection()
    user_ids = set(setup_roles_users_fresh_db.values())
    member_id = connection.execute(
        text("SELECT id FROM role WHERE name = 'account-member'")
    ).scalar_one()
    connection.execute(
        text("DELETE FROM roles_users WHERE role_id = :role_id"),
        {"role_id": member_id},
    )
    connection.execute(
        text("DELETE FROM role WHERE id = :role_id"),
        {"role_id": member_id},
    )

    migration = importlib.import_module(
        "flexmeasures.data.migrations.versions."
        "df847c1a72b0_grandfather_existing_members"
    )
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
    migration.upgrade()

    assigned_user_ids = set(
        connection.execute(
            text(
                "SELECT user_id FROM roles_users WHERE role_id = "
                "(SELECT id FROM role WHERE name = 'account-member')"
            )
        ).scalars()
    )
    assert user_ids <= assigned_user_ids
