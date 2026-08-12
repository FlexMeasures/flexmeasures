from __future__ import annotations

import logging

from sqlalchemy.exc import OperationalError, ProgrammingError

from flexmeasures.data import db, register_at
from flexmeasures.data.utils import (
    DatabaseSchemaRevisionStatus,
    format_database_schema_revision_status,
    get_database_schema_revision_status,
)
from flexmeasures.utils.sentry_utils import (
    SENTRY_DEDUPLICATION_KEY_ATTRIBUTE,
    _make_sentry_daily_deduplicator,
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


def test_schema_mismatch_log_record_is_deduplicated(
    app, clean_redis, monkeypatch, caplog
):
    """The schema check and Sentry filter share the LogRecord marker contract."""
    revision_status = DatabaseSchemaRevisionStatus(
        current_heads=("current-a",), expected_heads=("head-a",)
    )
    monkeypatch.setattr("flexmeasures.data.configure_db_for", lambda app: None)
    monkeypatch.setattr("flexmeasures.data.Migrate", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "flexmeasures.data._add_vacuum_option_to_db_upgrade", lambda app: None
    )
    monkeypatch.setattr(
        "flexmeasures.data._is_running_db_upgrade_command", lambda: False
    )
    monkeypatch.setattr("flexmeasures.data.ma.init_app", lambda app: None)
    monkeypatch.setattr(app, "teardown_request", lambda function: None)
    monkeypatch.setattr(app, "testing", False)
    monkeypatch.setitem(app.config, "FLEXMEASURES_ENV", "production")
    monkeypatch.setattr(
        "flexmeasures.data.utils.get_database_schema_revision_status",
        lambda app: revision_status,
    )

    with caplog.at_level(logging.ERROR):
        register_at(app)

    schema_mismatch_record = next(
        record
        for record in caplog.records
        if record.message.startswith(
            "Database schema is not at the Alembic head revision"
        )
    )
    assert (
        getattr(schema_mismatch_record, SENTRY_DEDUPLICATION_KEY_ATTRIBUTE)
        == "database-schema-mismatch:current-a:head-a"
    )

    deduplicate = _make_sentry_daily_deduplicator(
        app, redis_connection=app.redis_connection
    )
    event = {"message": schema_mismatch_record.getMessage()}
    hint = {"log_record": schema_mismatch_record}
    assert deduplicate(event, hint) is event
    assert deduplicate(event, hint) is None


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

    assert get_database_schema_revision_status(app).is_migrated_to_head is True


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

    assert get_database_schema_revision_status(app).is_migrated_to_head is False


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

    assert get_database_schema_revision_status(app).is_migrated_to_head is False


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
