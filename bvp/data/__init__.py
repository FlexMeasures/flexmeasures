from flask import Flask
from flask_migrate import Migrate

from bvp.data.config import configure_db, db
from bvp.data.auth_setup import configure_auth


def register_at(app: Flask):
    # First configure the central db object and Alembic's migration tool
    configure_db(app)
    Migrate(app, db)

    configure_auth(app, db)

    if app.cli:
        # Register some useful custom scripts with the flask cli
        with app.app_context():
            import bvp.data.cli_tasks.db_pop
            import bvp.data.cli_tasks.data_collection
            import bvp.data.cli_tasks.forecasting  # noqa: F401
