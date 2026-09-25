"""CLI commands for saving, resetting, etc of the database"""

from datetime import datetime
import subprocess

from flask import current_app as app
from flask.cli import with_appcontext
import flask_migrate as migrate
import click
from sqlalchemy.engine import make_url

from flexmeasures.cli.utils import LoggedClickExceptionGroup, MsgStyle


@click.group("db-ops", cls=LoggedClickExceptionGroup)
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
            click.secho("I did nothing.", **MsgStyle.WARN)
            raise click.Abort()
    from flexmeasures.data.scripts.data_gen import reset_db

    current_version = migrate.current()
    reset_db(app.db)
    migrate.stamp(current_version)


@fm_db_ops.command()
@with_appcontext
def dump():
    """
    Create a dump of all current data (using `pg_dump`).

    If you have a version mismatch between server and client, here is an alternative:


    $ docker run --pull=always -it postgres:15.7 bash  # use server version here

    $ docker exec -it <container> <the pg_dump command (see code)>

    $ docker cp <container>:<your-dump-filename> .

    $ docker stop <container>; docker rm <container>
    """
    db_uri = libpq_uri(app.config.get("SQLALCHEMY_DATABASE_URI"))
    db_host_and_db_name = db_uri.split("@")[-1]
    click.echo(f"Backing up {db_host_and_db_name} database")
    db_name = db_host_and_db_name.split("/")[-1]
    time_of_saving = datetime.now().strftime("%F-%H%M")
    dump_filename = f"pgbackup_{db_name}_{time_of_saving}.dump"
    # An argument list rather than a shell command, so that no character in the URI (e.g. in a password) can break it.
    command_for_dumping = [
        "pg_dump",
        "--no-privileges",
        "--no-owner",
        "--data-only",
        "--format=c",
        f"--file={dump_filename}",
        db_uri,
    ]
    try:
        subprocess.run(command_for_dumping, check=True)
        click.secho(f"db dump successful: saved to {dump_filename}", **MsgStyle.SUCCESS)

    # We report the exit code rather than the exception, whose command includes the URI and thus the password.
    except subprocess.CalledProcessError as e:
        click.secho(f"pg_dump exited with code {e.returncode}", **MsgStyle.ERROR)
        click.secho("db dump unsuccessful", **MsgStyle.ERROR)
    except OSError as e:
        click.secho(f"Could not run pg_dump: {e.strerror}", **MsgStyle.ERROR)
        click.secho("db dump unsuccessful", **MsgStyle.ERROR)


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

    db_uri = libpq_uri(app.config.get("SQLALCHEMY_DATABASE_URI"))
    db_host_and_db_name = db_uri.split("@")[-1]
    click.echo(f"Restoring {db_host_and_db_name} database from file {file}")
    # An argument list rather than a shell command, so that no character in the URI (e.g. in a password) can break it.
    command_for_restoring = ["pg_restore", "-d", db_uri, file]
    try:
        subprocess.run(command_for_restoring, check=True)
        click.secho("db restore successful", **MsgStyle.SUCCESS)

    # We report the exit code rather than the exception, whose command includes the URI and thus the password.
    except subprocess.CalledProcessError as e:
        click.secho(f"pg_restore exited with code {e.returncode}", **MsgStyle.ERROR)
        click.secho("db restore unsuccessful", **MsgStyle.ERROR)
    except OSError as e:
        click.secho(f"Could not run pg_restore: {e.strerror}", **MsgStyle.ERROR)
        click.secho("db restore unsuccessful", **MsgStyle.ERROR)


def libpq_uri(sqlalchemy_uri: str | None) -> str:
    """Turn a SQLAlchemy database URI into one that libpq tools (pg_dump, pg_restore) accept.

    libpq does not know SQLAlchemy's driver names (e.g. postgresql+psycopg2://),
    and would read such a URI as the name of a database on the local socket.
    """
    if not sqlalchemy_uri:
        raise click.ClickException("SQLALCHEMY_DATABASE_URI is not set.")
    url = make_url(sqlalchemy_uri)
    if url.get_backend_name() != "postgresql":
        raise click.ClickException(
            f"pg_dump and pg_restore need a PostgreSQL database, not {url.get_backend_name()}."
        )
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


app.cli.add_command(fm_db_ops)
