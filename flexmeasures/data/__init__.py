from flask import Flask
from flask_migrate import Migrate

from flexmeasures.data.config import configure_db_for, db
from flexmeasures.data.auth_setup import configure_auth
from flexmeasures.data.transactional import after_request_exception_rollback_session


def register_at(app: Flask):
    # First configure the central db object and Alembic's migration tool
    configure_db_for(app)
    Migrate(app, db)

    configure_auth(app, db)

    if app.cli:
        # Register some useful custom scripts with the flask cli
        with app.app_context():
            import flexmeasures.data.scripts.cli_tasks.background_workers
            import flexmeasures.data.scripts.cli_tasks.db_pop
            import flexmeasures.data.scripts.cli_tasks.data_collection
            import flexmeasures.data.scripts.cli_tasks.testing  # noqa: F401

    app.teardown_request(after_request_exception_rollback_session)
