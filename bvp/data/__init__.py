from flask import Flask
from flask_migrate import Migrate
from flask_security import Security, SQLAlchemySessionUserDatastore
from flask_login import user_logged_in
import click


def register(app: Flask):
    # First configure the central db object and Alembic's migration tool

    import bvp.data.config as db_config

    db_config.configure_db(app)
    Migrate(app, db_config.db)

    # Setup Flask-Security for user authentication & authorization

    from bvp.data.models.user import User, Role, remember_login
    user_datastore = SQLAlchemySessionUserDatastore(db_config.db.session, User, Role)
    app.security = Security(app, user_datastore)
    user_logged_in.connect(remember_login)

    # Register some useful custom scripts with the flask cli

    # @app.before_first_request
    @app.cli.command()
    @click.option(
        "--measurements/--no-measurements",
        default=False,
        help="Add measurements. May take long.",
    )
    @click.option(
        "--test-data-set/--no-test-data-set",
        default=False,
        help="Limit data set to a small one, useful for automated tests."
    )
    def db_populate(measurements: bool, test_data_set: bool):
        """Initialize the database with some static values."""
        from bvp.data.static_content import populate

        click.echo("Populating the database ...")
        populate(app, measurements, test_data_set)

    @app.cli.command()
    @click.option(
        "--force/--no-force", default=False, help="Skip warning about consequences."
    )
    def db_depopulate(force: bool):
        """Remove all values."""
        from bvp.data.static_content import depopulate

        click.echo("Depopulating the database ...")
        depopulate(app, force)
