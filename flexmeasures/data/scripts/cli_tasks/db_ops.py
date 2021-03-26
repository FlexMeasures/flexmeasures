"""CLI Tasks for saving, resetting, etc of the database"""

from datetime import datetime
import subprocess

from flask import current_app as app
from flask.cli import with_appcontext
import flask_migrate as migrate
import click


BACKUP_PATH = app.config.get("FLEXMEASURES_DB_BACKUP_PATH")


@click.group("db-ops")
def fm_db_ops():
    """FlexMeasures: Reset/Dump/Load/Restore/Save the DB."""


@fm_db_ops.command()
@with_appcontext
@click.option("--load", help="Reset to static data from file.")
@click.option("--dir", default=BACKUP_PATH, help="Directory for loading backups.")
@click.option(
    "--structure/--no-structure",
    default=False,
    help="Load structural data like asset (types), market (types),"
    " weather (sensors), users, roles.",
)
@click.option("--data/--no-data", default=False, help="Load (time series) data.")
def reset(
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
    """Save structure of the database to a backup file."""
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
    """Load structure and/or data for the database from a backup file."""
    if name:
        from flexmeasures.data.scripts.data_gen import load_tables

        load_tables(app.db, name, structure=structure, data=data, backup_path=dir)
    else:
        click.echo("You must specify the name of the backup: --name <unique name>")


@fm_db_ops.command()
@with_appcontext
def dump():
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


@fm_db_ops.command()
@with_appcontext
@click.argument("file", type=click.Path(exists=True))
def restore(file: str):
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


app.cli.add_command(fm_db_ops)
