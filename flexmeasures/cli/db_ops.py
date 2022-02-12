"""CLI Tasks for saving, resetting, etc of the database"""

from datetime import datetime, timedelta
import subprocess
from typing import List, Optional

from flask import current_app as app
from flask.cli import with_appcontext
import flask_migrate as migrate
import click
import pandas as pd

from flexmeasures.data import db
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.utils import save_to_db


BACKUP_PATH: str = app.config.get("FLEXMEASURES_DB_BACKUP_PATH")  # type: ignore


@click.group("db-ops")
def fm_db_ops():
    """FlexMeasures: Reset, Dump/Restore or Save/Load the DB data."""


@fm_db_ops.command()
@with_appcontext
def reset():
    """Reset database data and re-create tables from data model."""
    if not app.debug:
        prompt = (
            "This deletes all data and re-creates the tables on %s.\nDo you want to continue?"
            % app.db.engine
        )
        if not click.confirm(prompt):
            click.echo("I did nothing.")
            return
    from flexmeasures.data.scripts.data_gen import reset_db

    current_version = migrate.current()
    reset_db(app.db)
    migrate.stamp(current_version)


@fm_db_ops.command()
@with_appcontext
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
def save(name: str, dir: str = BACKUP_PATH, structure: bool = True, data: bool = False):
    """Backup db content to files."""
    if name:
        from flexmeasures.data.scripts.data_gen import save_tables

        save_tables(app.db, name, structure=structure, data=data, backup_path=dir)
    else:
        click.echo(
            "You must specify a unique name for the backup: --name <unique name>"
        )


@fm_db_ops.command()
@with_appcontext
@click.option("--name", help="Name of the backup.")
@click.option("--dir", default=BACKUP_PATH, help="Directory for loading backups.")
@click.option(
    "--structure/--no-structure",
    default=True,
    help="Load structural data like asset (types), market (types),"
    " weather (sensors), users, roles.",
)
@click.option("--data/--no-data", default=False, help="Load (time series) data.")
def load(name: str, dir: str = BACKUP_PATH, structure: bool = True, data: bool = False):
    """Load backed-up contents (see `db-ops save`), run `reset` first."""
    if name:
        from flexmeasures.data.scripts.data_gen import load_tables

        load_tables(app.db, name, structure=structure, data=data, backup_path=dir)
    else:
        click.echo("You must specify the name of the backup: --name <unique name>")


@fm_db_ops.command()
@with_appcontext
def dump():
    """Create a dump of all current data (using `pg_dump`)."""
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


@fm_db_ops.command()
@with_appcontext
@click.argument("file", type=click.Path(exists=True))
def restore(file: str):
    """Restore the dump file, see `db-ops dump` (run `reset` first).

    From the command line:

        % flexmeasures db-ops dump
        % flexmeasures db-ops reset
        % flexmeasures db-ops restore FILE

    """

    db_uri: str = app.config.get("SQLALCHEMY_DATABASE_URI")  # type: ignore
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


@fm_db_ops.command("resample-data")
@with_appcontext
@click.option(
    "--sensor-id",
    "sensor_ids",
    multiple=True,
    required=True,
    help="Resample data for this sensor. Follow up with the sensor's ID. This argument can be given multiple times.",
)
@click.option(
    "--event-resolution",
    "event_resolution_in_minutes",
    type=int,
    required=True,
    help="New event resolution as an integer number of minutes.",
)
@click.option(
    "--from",
    "start_str",
    required=False,
    help="Resample only data from this datetime onwards. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--until",
    "end_str",
    required=False,
    help="Resample only data until this datetime. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--skip-integrity-check",
    is_flag=True,
    help="Whether to skip checking the resampled time series data for each sensor."
    " By default, an excerpt and the mean value of the original"
    " and resampled data will be shown for manual approval.",
)
def resample_sensor_data(
    sensor_ids: List[int],
    event_resolution_in_minutes: int,
    start_str: Optional[str] = None,
    end_str: Optional[str] = None,
    skip_integrity_check: bool = False,
):
    """Assign a new event resolution to an existing sensor and resample its data accordingly."""
    event_resolution = timedelta(minutes=event_resolution_in_minutes)
    event_starts_after = pd.Timestamp(start_str)  # note that "" or None becomes NaT
    event_ends_before = pd.Timestamp(end_str)
    for sensor_id in sensor_ids:
        sensor = Sensor.query.get(sensor_id)
        if sensor.event_resolution == event_resolution:
            print(f"{sensor} already has the desired event resolution.")
            continue
        df_original = sensor.search_beliefs(
            most_recent_beliefs_only=False,
            event_starts_after=event_starts_after,
            event_ends_before=event_ends_before,
        ).sort_values("event_start")
        df_resampled = df_original.resample_events(event_resolution).sort_values(
            "event_start"
        )
        if not skip_integrity_check:
            message = ""
            if sensor.event_resolution < event_resolution:
                message += f"Downsampling {sensor} to {event_resolution} will result in a loss of data. "
            click.confirm(
                message
                + f"Data before:\n{df_original}\nData after:\n{df_resampled}\nMean before: {df_original['event_value'].mean()}\nMean after: {df_resampled['event_value'].mean()}\nContinue?",
                abort=True,
            )

        # Update sensor
        sensor.event_resolution = event_resolution
        db.session.add(sensor)

        # Update sensor data
        query = TimedBelief.query.filter(TimedBelief.sensor == sensor)
        if not pd.isnull(event_starts_after):
            query = query.filter(TimedBelief.event_start >= event_starts_after)
        if not pd.isnull(event_ends_before):
            query = query.filter(
                TimedBelief.event_start + sensor.event_resolution <= event_ends_before
            )
        query.delete()
        save_to_db(df_resampled, bulk_save_objects=True)
    db.session.commit()
    print("Successfully resampled sensor data.")


app.cli.add_command(fm_db_ops)
