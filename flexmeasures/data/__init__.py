"""
Models & schemata, as well as business logic (queries & services).
"""

import functools
import os
import sys

import click
from flask import Flask
from flask_migrate import Migrate
from flask_migrate.cli import db as db_cli_group
from flask_marshmallow import Marshmallow
from sqlalchemy import text

from flexmeasures.data.config import configure_db_for, db
from flexmeasures.data.transactional import after_request_exception_rollback_session


ma: Marshmallow = Marshmallow()


def _is_running_db_upgrade_command() -> bool:
    """Return whether this process is already running the Alembic upgrade command."""
    args = sys.argv[1:]
    return any(args[i : i + 2] == ["db", "upgrade"] for i in range(len(args) - 1))


def _add_vacuum_option_to_db_upgrade(app: Flask):
    """Extend `flexmeasures db upgrade` to vacuum-analyze the database afterwards.

    After schema migrations, Postgres' planner statistics can be stale, leading to
    poor query plans. Running VACUUM ANALYZE right after upgrading avoids that.
    """
    upgrade_command = db_cli_group.commands["upgrade"]
    if getattr(upgrade_command, "_fm_vacuum_option_added", False):
        return
    upgrade_command._fm_vacuum_option_added = True
    upgrade_command.params.append(
        click.Option(
            ["--vacuum/--no-vacuum"],
            default=True,
            show_default=True,
            help="Run VACUUM ANALYZE after upgrading, refreshing the query planner's statistics.",
        )
    )
    original_callback = upgrade_command.callback

    @functools.wraps(original_callback)
    def upgrade_then_vacuum(*args, vacuum: bool = True, **kwargs):
        result = original_callback(*args, **kwargs)
        if vacuum and not kwargs.get("sql"):
            click.echo("Running VACUUM ANALYZE ...")
            with db.engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as connection:
                connection.execute(text("VACUUM ANALYZE"))
        return result

    upgrade_command.callback = upgrade_then_vacuum


def register_at(app: Flask):
    # First configure the central db object and Alembic's migration tool
    configure_db_for(app)
    Migrate(app, db, directory=os.path.join(app.root_path, "data", "migrations"))
    _add_vacuum_option_to_db_upgrade(app)

    app.database_schema_is_migrated_to_head = True
    if not app.testing and app.config.get("FLEXMEASURES_ENV") != "documentation":
        from flexmeasures.data.utils import (
            format_database_schema_revision_status,
            get_database_schema_revision_status,
        )

        revision_status = get_database_schema_revision_status(app)
        app.database_schema_is_migrated_to_head = revision_status.is_migrated_to_head
        if (
            not app.database_schema_is_migrated_to_head
            and not _is_running_db_upgrade_command()
        ):
            if revision_status.inspection_error is not None:
                app.logger.error(
                    "Could not determine the database schema revision. "
                    "Check database connectivity and configuration before starting the app. "
                    f"Details: {revision_status.inspection_error}"
                )
            else:
                app.logger.error(
                    "Database schema is not at the Alembic head revision "
                    f"({format_database_schema_revision_status(revision_status)}). "
                    "Run `flexmeasures db upgrade` before starting the app."
                )

    global ma
    ma.init_app(app)

    app.teardown_request(after_request_exception_rollback_session)
