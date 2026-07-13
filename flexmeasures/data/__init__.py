"""
Models & schemata, as well as business logic (queries & services).
"""

import os

from flask import Flask
from flask_migrate import Migrate
from flask_marshmallow import Marshmallow

from flexmeasures.data.config import configure_db_for, db
from flexmeasures.data.transactional import after_request_exception_rollback_session


ma: Marshmallow = Marshmallow()


def register_at(app: Flask):
    # First configure the central db object and Alembic's migration tool
    configure_db_for(app)
    Migrate(app, db, directory=os.path.join(app.root_path, "data", "migrations"))

    app.database_schema_is_migrated_to_head = True
    if not app.testing and app.config.get("FLEXMEASURES_ENV") != "documentation":
        from flexmeasures.data.utils import database_schema_is_migrated_to_head

        app.database_schema_is_migrated_to_head = database_schema_is_migrated_to_head(
            app
        )
        if not app.database_schema_is_migrated_to_head:
            app.logger.warning(
                "Database schema is not at the Alembic head revision. Run `flexmeasures db upgrade` before starting the app."
            )

    global ma
    ma.init_app(app)

    app.teardown_request(after_request_exception_rollback_session)
