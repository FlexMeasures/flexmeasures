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
        "--structure/--no-structure",
        default=False,
        help="Populate structural data like asset (types), market (types), users, roles.",
    )
    @click.option(
        "--data/--no-data",
        default=False,
        help="Populate (time series) data. Will do nothing without structural data present. Data links into structure.",
    )
    @click.option(
        "--small/--no-small",
        default=False,
        help="Limit data set to a small one, useful for automated tests.",
    )
    def db_populate(structure: bool, data: bool, small: bool):
        """Initialize the database with static values."""
        if structure:
            from bvp.data.static_content import populate_structure

            populate_structure(app, small)
        if data:
            from bvp.data.static_content import populate_time_series_data

            populate_time_series_data(app, small)
        if not structure and not data:
            click.echo(
                "I did nothing as neither --structure nor --data was given. Decide what you want!"
            )

    @app.cli.command()
    @click.option(
        "--structure/--no-structure",
        default=False,
        help="Depopulate structural data like asset (types), market (types),"
        " weather (sensors), users, roles.",
    )
    @click.option(
        "--data/--no-data", default=False, help="Depopulate (time series) data."
    )
    @click.option(
        "--force/--no-force", default=False, help="Skip warning about consequences."
    )
    def db_depopulate(structure: bool, data: bool, force: bool):
        """Remove all values."""
        if not data and not structure:
            click.echo("Neither --data nor --structure given ... doing nothing.")
            return
        if not force and (data or structure):
            affected_tables = []
            if structure:
                affected_tables += [
                    "MarketType",
                    "Market",
                    "AssetType",
                    "Asset",
                    "WeatherSensorType",
                    "WeatherSensor",
                    "Role",
                    "User",
                ]
            if data:
                affected_tables += ["Power", "Price", "Weather"]
            prompt = (
                "This deletes all %s entries from %s.\nDo you want to continue?"
                % (
                    " and ".join(", ".join(affected_tables).rsplit(", ", 1)),
                    app.config.get("SQLALCHEMY_DATABASE_URI"),
                )
            )
            if not click.confirm(prompt):
                return
        if data:
            from bvp.data.static_content import depopulate_data

            depopulate_data(app)
        if structure:
            from bvp.data.static_content import depopulate_structure

            depopulate_structure(app)

    @app.cli.command()
    def db_reset():
        """Initialize the database with static values."""
        if not app.debug:
            prompt = (
                "This deletes all data and resets the structure on %s.\nDo you want to continue?"
                % app.config.get("SQLALCHEMY_DATABASE_URI")
            )
            if not click.confirm(prompt):
                click.echo("I did nothing.")
                return
        from bvp.data.static_content import reset_db

        reset_db(app)
