from flask import Flask
from flask_migrate import Migrate
from flask_caching import Cache

from bvp.data.config import configure_db_for, db
from bvp.data.auth_setup import configure_auth
from bvp.data.transactional import after_request_session_commit_or_rollback


def register_at(app: Flask):
    app.cache = Cache(app, config={"CACHE_TYPE": "data.services.caching.simple"})
    # First configure the central db object and Alembic's migration tool
    configure_db_for(app)
    Migrate(app, db)

    configure_auth(app, db)

    if app.cli:
        # Register some useful custom scripts with the flask cli
        with app.app_context():
            import bvp.data.scripts.cli_tasks.background_workers
            import bvp.data.scripts.cli_tasks.db_pop
            import bvp.data.scripts.cli_tasks.data_collection
            import bvp.data.scripts.cli_tasks.testing  # noqa: F401

    app.teardown_request(after_request_session_commit_or_rollback)
