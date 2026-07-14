"""
Models & schemata, as well as business logic (queries & services).
"""

import os
import sys

from flask import Flask
from flask_migrate import Migrate
from flask_marshmallow import Marshmallow

from flexmeasures.data.config import configure_db_for, db
from flexmeasures.data.transactional import after_request_exception_rollback_session


ma: Marshmallow = Marshmallow()


def _is_running_db_upgrade_command() -> bool:
    """Return whether this process is already running the Alembic upgrade command."""
    args = sys.argv[1:]
    return any(args[i : i + 2] == ["db", "upgrade"] for i in range(len(args) - 1))


def register_at(app: Flask):
    # First configure the central db object and Alembic's migration tool
    configure_db_for(app)
    Migrate(app, db, directory=os.path.join(app.root_path, "data", "migrations"))

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
