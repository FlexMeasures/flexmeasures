"""CLI Tasks for (de)populating the database - most useful in development"""


from flask import current_app as app
import flask_migrate as migrate
import click

from bvp.data.scripts.static_content import get_affected_classes

BACKUP_PATH = app.config.get("BVP_DB_BACKUP_PATH")


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
    "--forecasts/--no-forecasts",
    default=False,
    help="Populate (time series) forecasts. Will do nothing without structural data present. Data links into structure.",
)
@click.option(
    "--small/--no-small",
    default=False,
    help="Limit data set to a small one, useful for automated tests.",
)
@click.option(
    "--type",
    help="Populate (time series) data for a specific generic asset type only. Follow up with Asset, Market or WeatherSensor.",
)
@click.option(
    "--asset",
    help="Populate (time series) data for a single asset only. Follow up with the asset's name.",
)
@click.option(
    "--from_date",
    default="2015-02-08",
    help="Forecast from date (inclusive). Follow up with a date in the form yyyy-mm-dd.",
)
@click.option(
    "--to_date",
    default="2015-12-31",
    help="Forecast to date (inclusive). Follow up with a date in the form yyyy-mm-dd.",
)
@click.option(
    "--save",
    help="Save the populated data to file. Follow up with a unique name for this backup.",
)
@click.option("--dir", default=BACKUP_PATH, help="Directory for saving backups.")
def db_populate(
    structure: bool,
    data: bool,
    forecasts: bool,
    small: bool,
    save: str,
    dir: str,
    type: str = None,
    from_date: str = "2015-02-08",
    to_date: str = "2015-12-31",
    asset: str = None,
):
    """Initialize the database with static values."""
    if structure:
        from bvp.data.scripts.static_content import populate_structure

        populate_structure(app.db, small)
    if data:
        from bvp.data.scripts.static_content import populate_time_series_data

        populate_time_series_data(app.db, small, type, asset)
    if forecasts:
        from bvp.data.scripts.static_content import populate_time_series_forecasts

        populate_time_series_forecasts(app.db, small, type, asset, from_date, to_date)
    if not structure and not data and not forecasts:
        click.echo(
            "I did nothing as neither --structure nor --data nor --forecasts was given. Decide what you want!"
        )
    if save:
        from bvp.data.scripts.static_content import save_tables

        if data and not small:
            click.echo("Too much data to save! I'm only saving structure ...")
            save_tables(app.db, save, structure, data=False, backup_path=dir)
        else:
            save_tables(app.db, save, structure, data, dir)


@app.cli.command()
@click.option(
    "--structure/--no-structure",
    default=False,
    help="Depopulate structural data like asset (types), market (types),"
    " weather (sensors), users, roles.",
)
@click.option("--data/--no-data", default=False, help="Depopulate (time series) data.")
@click.option(
    "--forecasts/--no-forecasts",
    default=False,
    help="Depopulate (time series) forecasts.",
)
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
@click.option(
    "--type",
    help="Populate (time series) data for a specific generic asset type only."
    "Follow up with Asset, Market or WeatherSensor.",
)
@click.option(
    "--asset",
    help="Depopulate (time series) data for a single asset only. Follow up with the asset's name.",
)
def db_depopulate(
    structure: bool,
    data: bool,
    forecasts: bool,
    force: bool,
    type: str = None,
    asset: str = None,
):
    """Remove all values."""
    if not data and not structure and not forecasts:
        click.echo(
            "Neither --data nor --forecasts nor --structure given ... doing nothing."
        )
        return
    if not force and (data or structure or forecasts):
        affected_tables = get_affected_classes(structure, data or forecasts)
        prompt = "This deletes all %s entries from %s.\nDo you want to continue?" % (
            " and ".join(
                ", ".join(
                    [affected_table.__tablename__ for affected_table in affected_tables]
                ).rsplit(", ", 1)
            ),
            app.db.engine,
        )
        if not click.confirm(prompt):
            return
    if forecasts:
        from bvp.data.scripts.static_content import depopulate_forecasts

        depopulate_forecasts(app.db, type, asset)
    if data:
        from bvp.data.scripts.static_content import depopulate_data

        depopulate_data(app.db, type, asset)
    if structure:
        from bvp.data.scripts.static_content import depopulate_structure

        depopulate_structure(app.db)


@app.cli.command()
@click.option("--load", help="Reset to static data from file.")
@click.option("--dir", default=BACKUP_PATH, help="Directory for loading backups.")
@click.option(
    "--structure/--no-structure",
    default=False,
    help="Load structural data like asset (types), market (types),"
    " weather (sensors), users, roles.",
)
@click.option("--data/--no-data", default=False, help="Load (time series) data.")
def db_reset(
    load: str = None, dir: str = BACKUP_PATH, structure: bool = True, data: bool = False
):
    """Initialize the database with static values."""
    if not app.debug:
        prompt = (
            "This deletes all data and resets the structure on %s.\nDo you want to continue?"
            % app.db.engine
        )
        if not click.confirm(prompt):
            click.echo("I did nothing.")
            return
    from bvp.data.scripts.static_content import reset_db

    current_version = migrate.current()
    reset_db(app.db)
    migrate.stamp(current_version)

    if load:
        if not data and not structure:
            click.echo("Neither --data nor --structure given ... loading nothing.")
            return
        from bvp.data.scripts.static_content import load_tables

        load_tables(app.db, load, structure, data, dir)


@app.cli.command()
@click.option("--name", help="Unique name for saving the backup.")
@click.option("--dir", default=BACKUP_PATH, help="Directory for saving backups.")
@click.option(
    "--structure/--no-structure",
    default=True,
    help="Save structural data like asset (types), market (types),"
    " weather (sensors), users, roles.",
)
@click.option(
    "--data/--no-data",
    default=False,
    help="Save (time series) data. Only do this for small data sets!",
)
def db_save(
    name: str, dir: str = BACKUP_PATH, structure: bool = True, data: bool = False
):
    """Save structure of the database to a backup file."""
    if name:
        from bvp.data.scripts.static_content import save_tables

        save_tables(app.db, name, structure=structure, data=data, backup_path=dir)
    else:
        click.echo(
            "You must specify a unique name for the backup: --name <unique name>"
        )


@app.cli.command()
@click.option("--name", help="Name of the backup.")
@click.option("--dir", default=BACKUP_PATH, help="Directory for loading backups.")
@click.option(
    "--structure/--no-structure",
    default=True,
    help="Load structural data like asset (types), market (types),"
    " weather (sensors), users, roles.",
)
@click.option("--data/--no-data", default=False, help="Load (time series) data.")
def db_load(
    name: str, dir: str = BACKUP_PATH, structure: bool = True, data: bool = False
):
    """Load structure and/or data for the database from a backup file."""
    if name:
        from bvp.data.scripts.static_content import load_tables

        load_tables(app.db, name, structure=structure, data=data, backup_path=dir)
    else:
        click.echo("You must specify the name of the backup: --name <unique name>")
