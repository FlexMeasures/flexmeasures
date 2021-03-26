"""CLI Tasks for (de)populating the database - most useful in development"""

from datetime import datetime, timedelta
import subprocess
from typing import List

import pandas as pd
import pytz
from flask import current_app as app
import flask_migrate as migrate
from flask_security.utils import hash_password
import click
import getpass

from flexmeasures.data.services.forecasting import create_forecasting_jobs
from flexmeasures.data.services.users import (
    create_user,
    find_user_by_email,
    delete_user,
)
from flexmeasures.data.scripts.data_gen import get_affected_classes
from flexmeasures.data.models.assets import Asset, AssetSchema


BACKUP_PATH = app.config.get("FLEXMEASURES_DB_BACKUP_PATH")


@app.cli.command()
@click.option("--username", required=True)
@click.option("--email", required=True)
@click.option("--roles", help="e.g. anonymous,Prosumer,CPO")
@click.option(
    "--timezone",
    default="UTC",
    help="timezone as string, e.g. 'UTC' or 'Europe/Amsterdam'",
)
def new_user(username: str, email: str, roles: List[str], timezone: str):
    """
    Create a FlexMeasures user.

    The `users create` task from Flask Security Too is too simple for us.
    Use this to add email, timezone and roles.
    """
    try:
        pytz.timezone(timezone)
    except pytz.UnknownTimeZoneError:
        print("Timezone %s is unknown!" % timezone)
        raise click.Abort
    pwd1 = getpass.getpass(prompt="Please enter the password:")
    pwd2 = getpass.getpass(prompt="Please repeat the password:")
    if pwd1 != pwd2:
        print("Passwords do not match!")
        raise click.Abort
    created_user = create_user(
        username=username,
        email=email,
        password=hash_password(pwd1),
        timezone=timezone,
        user_roles=roles,
        check_deliverability=False,
    )
    app.db.session.commit()
    print(f"Successfully created user {created_user}")


@app.cli.command()
@click.option("--email")
def delete_user_and_data(email: str):
    """
    Delete a user, which also deletes their data.
    """
    the_user = find_user_by_email(email)
    if the_user is None:
        print(f"Could not find user with email address '{email}' ...")
        return
    delete_user(the_user)
    app.db.session.commit()


@app.cli.command()
@click.option("--name", required=True)
@click.option("--asset-type-name", required=True)
@click.option("--unit", required=True, help="e.g. MW, kW/h", default="MW")
@click.option("--capacity-in-MW", required=True, type=float)
@click.option(
    "--event-resolution",
    required=True,
    type=int,
    help="Expected resolution of the data in minutes",
)
@click.option(
    "--latitude",
    required=True,
    type=float,
    help="Latitude of the asset's location",
)
@click.option(
    "--longitude",
    required=True,
    type=float,
    help="Longitude of the asset's location",
)
@click.option(
    "--owner-id", required=True, type=int, help="Id of the user who owns this asset."
)
@click.option(
    "--market-id",
    required=True,
    type=int,
    help="Id of the market used to price this asset.",
)
@click.option(
    "--timezone",
    default="UTC",
    help="timezone as string, e.g. 'UTC' or 'Europe/Amsterdam'",
)
def new_asset(**args):
    """
    Create a new asset.
    """
    try:
        pytz.timezone(args["timezone"])
    except pytz.UnknownTimeZoneError:
        print("Timezone %s is unknown!" % args["timezone"])
        raise click.Abort
    # TODO: if no market, select dummy market
    errors = AssetSchema().validate(args)
    if errors:
        print(
            f"Please correct the following errors:\n{errors}.\n Use the --help flag to learn more."
        )
        raise click.Abort
    args["event_resolution"] = timedelta(minutes=args["event_resolution"])
    asset = Asset(**args)
    app.db.session.add(asset)
    app.db.session.commit()
    print(
        f"Successfully created asset with ID:{asset.id}."
        f" You can access it at its entity address {asset.entity_address}"
    )


# @app.before_first_request
@app.cli.command()
@click.option(
    "--structure/--no-structure",
    default=False,
    help="Populate structural data (right now: asset types).",
)
@click.option(
    "--forecasts/--no-forecasts",
    default=False,
    help="Populate (time series) forecasts. Will do nothing without structural data present. Data links into structure.",
)
@click.option(
    "--asset-type",
    help="Populate (time series) data for a specific generic asset type only."
    " Follow up with Asset, Market or WeatherSensor.",
)
@click.option(
    "--asset",
    help="Populate (time series) data for a single asset only. Follow up with the asset's name. "
    "Use in combination with --asset-type, so we know where to look this name up.",
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
def db_populate(
    structure: bool,
    forecasts: bool,
    asset_type: str = None,
    from_date: str = "2015-02-08",
    to_date: str = "2015-12-31",
    asset: str = None,
):
    """Initialize the database with static values.
    TODO: split into a function for structural data and one for forecasts.
    """
    if structure:
        from flexmeasures.data.scripts.data_gen import populate_structure

        populate_structure(app.db)
    if forecasts:
        from flexmeasures.data.scripts.data_gen import populate_time_series_forecasts

        populate_time_series_forecasts(app.db, asset_type, asset, from_date, to_date)
    if not structure and not forecasts:
        click.echo(
            "I did nothing as neither --structure nor --forecasts was given. Decide what you want!"
        )


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
    "--asset-type",
    help="Depopulate (time series) data for a specific generic asset type only."
    "Follow up with Asset, Market or WeatherSensor.",
)
@click.option(
    "--asset",
    help="Depopulate (time series) data for a single asset only. Follow up with the asset's name. "
    "Use in combination with --asset-type, so we know where to look this name up.",
)
def db_depopulate(
    structure: bool,
    data: bool,
    forecasts: bool,
    force: bool,
    asset_type: str = None,
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
        from flexmeasures.data.scripts.data_gen import depopulate_forecasts

        depopulate_forecasts(app.db, asset_type, asset)
    if data:
        from flexmeasures.data.scripts.data_gen import depopulate_data

        depopulate_data(app.db, asset_type, asset)
    if structure:
        from flexmeasures.data.scripts.data_gen import depopulate_structure

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
    """Reset database, with options to load fresh data."""
    if not app.debug:
        prompt = (
            "This deletes all data and resets the structure on %s.\nDo you want to continue?"
            % app.db.engine
        )
        if not click.confirm(prompt):
            click.echo("I did nothing.")
            return
    from flexmeasures.data.scripts.data_gen import reset_db

    current_version = migrate.current()
    reset_db(app.db)
    migrate.stamp(current_version)

    if load:
        if not data and not structure:
            click.echo("Neither --data nor --structure given ... loading nothing.")
            return
        from flexmeasures.data.scripts.data_gen import load_tables

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
    help="Save (time series) data to a backup. Only do this for small data sets!",
)
def db_save(
    name: str, dir: str = BACKUP_PATH, structure: bool = True, data: bool = False
):
    """Save structure of the database to a backup file."""
    if name:
        from flexmeasures.data.scripts.data_gen import save_tables

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
        from flexmeasures.data.scripts.data_gen import load_tables

        load_tables(app.db, name, structure=structure, data=data, backup_path=dir)
    else:
        click.echo("You must specify the name of the backup: --name <unique name>")


@app.cli.command()
@click.option("--asset-id", help="Asset id.")
@click.option(
    "--from-date",
    help="Forecast from date (inclusive). Follow up with a date in the form yyyy-mm-dd.",
)
@click.option(
    "--to-date",
    help="Forecast to date (exclusive!). Follow up with a date in the form yyyy-mm-dd.",
)
@click.option("--horizon-hours", default=1, help="Forecasting horizon in hours.")
def create_power_forecasts(
    asset_id: int,
    from_date: str,
    to_date: str,
    timezone: str = "Asia/Seoul",
    horizon_hours: int = 1,
):
    """Creates a forecasting job.

    Useful to run locally and create forecasts on a remote server. In that case, just point the redis db in your
    config settings to that of the remote server. To process the job, run a worker to process the forecasting queue.

    For example:

        from_data = "2015-02-02"
        to_date = "2015-02-04"
        horizon_hours = 6

        This creates 1 job that forecasts values from 0am on May 2nd to 0am on May 4th,
        based on a 6 hour horizon.
        Note that this time period refers to the period of events we are forecasting, while in create_forecasting_jobs
        the time period refers to the period of belief_times, therefore we are subtracting the horizon.
    """
    create_forecasting_jobs(
        asset_id=asset_id,
        timed_value_type="Power",
        horizons=[timedelta(hours=horizon_hours)],
        start_of_roll=pd.Timestamp(from_date).tz_localize(timezone)
        - timedelta(hours=horizon_hours),
        end_of_roll=pd.Timestamp(to_date).tz_localize(timezone)
        - timedelta(hours=horizon_hours),
    )


@app.cli.command()
def db_dump():
    """Create a database dump of the database used by the app."""
    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    db_host_and_db_name = db_uri.split("@")[-1]
    click.echo(f"Backing up {db_host_and_db_name} database")
    db_name = db_host_and_db_name.split("/")[-1]
    time_of_saving = datetime.now().strftime("%F-%H%M")
    dump_filename = f"pgbackup_{db_name}_{time_of_saving}.dump"
    command_for_dumping = f"pg_dump --no-privileges --no-owner --data-only --format=c --file={dump_filename} {db_uri}"
    try:
        proc = subprocess.Popen(command_for_dumping, shell=True)  # , env={
        # 'PGPASSWORD': DB_PASSWORD
        # })
        proc.wait()
        click.echo(f"db dump successful: saved to {dump_filename}")

    except Exception as e:
        click.echo(f"Exception happened during dump: {e}")
        click.echo("db dump unsuccessful")


@app.cli.command()
@click.argument("file", type=click.Path(exists=True))
def db_restore(file: str):
    """Restore the database used by the app, from a given database dump file, after you've reset the database.

    From the command line:

        % db-dump
        % db-reset
        % db-restore FILE

    """

    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    db_host_and_db_name = db_uri.split("@")[-1]
    click.echo(f"Restoring {db_host_and_db_name} database from file {file}")
    command_for_restoring = f"pg_restore -d {db_uri} {file}"
    try:
        proc = subprocess.Popen(command_for_restoring, shell=True)  # , env={
        # 'PGPASSWORD': DB_PASSWORD
        # })
        proc.wait()
        click.echo("db restore successful")

    except Exception as e:
        click.echo(f"Exception happened during restore: {e}")
        click.echo("db restore unsuccessful")
