from flask import Flask
from flask_migrate import Migrate
import click

from bvp.data.config import configure_db, db
from bvp.data.auth_setup import configure_auth


def register_at(app: Flask):
    # First configure the central db object and Alembic's migration tool
    configure_db(app)
    Migrate(app, db)

    configure_auth(app, db)

    # Register some useful custom scripts with the flask cli
    register_db_maintenance_tasks(app)
    register_data_collection_tasks(app)


def register_db_maintenance_tasks(app: Flask):

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


def register_data_collection_tasks(app):
    """Any tasks to collect third-party data."""

    @app.cli.command()
    @click.option("--num_cells", default=1, help="Number of cells on the grid.")
    @click.option(
        "--method",
        default="hex",
        type=click.Choice(["hex", "square"]),
        help="Grid creation method.",
    )
    @click.option(
        "--top", type=float, required=True, help="Top latitude for region of interest."
    )
    @click.option(
        "--left",
        type=float,
        required=True,
        help="Left longitude for region of interest.",
    )
    @click.option(
        "--bottom",
        type=float,
        required=True,
        help="Bottom latitude for region of interest.",
    )
    @click.option(
        "--right",
        type=float,
        required=True,
        help="Right longitude for region of interest.",
    )
    def collect_weather_data(num_cells, method, top, left, bottom, right):
        """Collect weather data"""
        from bvp.data.scripts.grid_weather import get_weather_forecasts

        get_weather_forecasts(app, num_cells, method, top, left, bottom, right)
