import os

from flask import Flask
from flask_migrate import Migrate
from flask_marshmallow import Marshmallow

from flexmeasures.data.config import configure_db_for, db
from flexmeasures.data.auth_setup import configure_auth
from flexmeasures.data.transactional import after_request_exception_rollback_session


ma: Marshmallow = Marshmallow()


def register_at(app: Flask):
    # First configure the central db object and Alembic's migration tool
    configure_db_for(app)
    Migrate(app, db, directory=os.path.join(app.root_path, "data", "migrations"))

    global ma
    ma.init_app(app)

    configure_auth(app, db)

    if app.cli:
        # Register some useful custom scripts with the flask cli
        with app.app_context():
            import flexmeasures.data.scripts.cli_tasks.jobs
            import flexmeasures.data.scripts.cli_tasks.data_add
            import flexmeasures.data.scripts.cli_tasks.data_delete
            import flexmeasures.data.scripts.cli_tasks.db_ops
            import flexmeasures.data.scripts.cli_tasks.testing  # noqa: F401

    app.teardown_request(after_request_exception_rollback_session)
