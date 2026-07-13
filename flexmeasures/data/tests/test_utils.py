from __future__ import annotations

from sqlalchemy.exc import OperationalError, ProgrammingError

from flexmeasures.data import db
from flexmeasures.data.utils import (
    database_schema_is_migrated_to_head,
    format_database_schema_revision_status,
    get_database_schema_revision_status,
)


class _DummyConnection:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyMigrationContext:
    def __init__(self, heads: tuple[str, ...]):
        self._heads = heads

    def get_current_heads(self) -> tuple[str, ...]:
        return self._heads


class _DummyScriptDirectory:
    def __init__(self, heads: tuple[str, ...]):
        self._heads = heads

    def get_heads(self) -> tuple[str, ...]:
        return self._heads


def test_database_schema_is_migrated_to_head_when_revisions_match(app, monkeypatch):
    monkeypatch.setattr(db.engine, "connect", lambda: _DummyConnection())
    monkeypatch.setattr(
        "flexmeasures.data.utils.MigrationContext.configure",
        lambda connection: _DummyMigrationContext(("head-a",)),
    )
    monkeypatch.setattr(
        "flexmeasures.data.utils.ScriptDirectory.from_config",
        lambda config: _DummyScriptDirectory(("head-a",)),
    )

    assert database_schema_is_migrated_to_head(app) is True


def test_database_schema_revision_status_includes_current_and_expected_heads(
    app, monkeypatch
):
    monkeypatch.setattr(db.engine, "connect", lambda: _DummyConnection())
    monkeypatch.setattr(
        "flexmeasures.data.utils.MigrationContext.configure",
        lambda connection: _DummyMigrationContext(("current-a",)),
    )
    monkeypatch.setattr(
        "flexmeasures.data.utils.ScriptDirectory.from_config",
        lambda config: _DummyScriptDirectory(("head-a",)),
    )

    status = get_database_schema_revision_status(app)

    assert status.current_heads == ("current-a",)
    assert status.expected_heads == ("head-a",)
    assert status.is_migrated_to_head is False
    assert (
        format_database_schema_revision_status(status)
        == "current revision(s): current-a; head revision(s): head-a"
    )


def test_database_schema_is_not_migrated_to_head_when_revisions_differ(
    app, monkeypatch
):
    monkeypatch.setattr(db.engine, "connect", lambda: _DummyConnection())
    monkeypatch.setattr(
        "flexmeasures.data.utils.MigrationContext.configure",
        lambda connection: _DummyMigrationContext(("current-a",)),
    )
    monkeypatch.setattr(
        "flexmeasures.data.utils.ScriptDirectory.from_config",
        lambda config: _DummyScriptDirectory(("head-a",)),
    )

    assert database_schema_is_migrated_to_head(app) is False


def test_database_schema_is_not_migrated_to_head_when_revision_lookup_fails(
    app, monkeypatch
):
    def raise_programming_error():
        raise ProgrammingError(
            "SELECT version_num FROM alembic_version",
            None,
            Exception("relation alembic_version does not exist"),
        )

    monkeypatch.setattr(db.engine, "connect", raise_programming_error)
    monkeypatch.setattr(
        "flexmeasures.data.utils.ScriptDirectory.from_config",
        lambda config: _DummyScriptDirectory(("head-a",)),
    )

    assert database_schema_is_migrated_to_head(app) is False


def test_database_schema_revision_status_records_connectivity_failure(app, monkeypatch):
    def raise_operational_error():
        raise OperationalError(
            "SELECT version_num FROM alembic_version",
            None,
            Exception("could not connect to server"),
        )

    monkeypatch.setattr(db.engine, "connect", raise_operational_error)
    monkeypatch.setattr(
        "flexmeasures.data.utils.ScriptDirectory.from_config",
        lambda config: _DummyScriptDirectory(("head-a",)),
    )

    status = get_database_schema_revision_status(app)

    assert status.current_heads == ()
    assert status.expected_heads == ("head-a",)
    assert status.inspection_error is not None
    assert status.is_migrated_to_head is False
