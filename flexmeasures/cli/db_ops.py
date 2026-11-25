"""CLI commands for saving, resetting, etc of the database"""

from datetime import datetime
import subprocess

from flask import current_app as app
from flask.cli import with_appcontext
import flask_migrate as migrate
import click
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from flexmeasures.cli.utils import LoggedClickExceptionGroup, MsgStyle
from flexmeasures.data import db
from flexmeasures.data.services import timescaledb


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
        raise click.Abort()
    except OSError as e:
        click.secho(f"Could not run pg_dump: {e.strerror}", **MsgStyle.ERROR)
        click.secho("db dump unsuccessful", **MsgStyle.ERROR)
        raise click.Abort()


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
        raise click.Abort()
    except OSError as e:
        click.secho(f"Could not run pg_restore: {e.strerror}", **MsgStyle.ERROR)
        click.secho("db restore unsuccessful", **MsgStyle.ERROR)
        raise click.Abort()


@fm_db_ops.command("enable-timescaledb")
@with_appcontext
@click.option(
    "--chunk-time-interval",
    default="7 days",
    show_default=True,
    help="How much event time each chunk of the timed_belief table spans, as a PostgreSQL interval."
    " Aim for the most recent chunks, with their indexes, to fit in memory.",
)
@click.option(
    "--compress-after",
    default=None,
    help="Also compress chunks whose events are all older than this PostgreSQL interval (e.g. '30 days'),"
    " now and from now on. Compressed data still accepts writes, but more slowly.",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Do not ask for confirmation.",
)
def enable_timescaledb(chunk_time_interval: str, compress_after: str | None, yes: bool):
    """Store time series data in a TimescaleDB hypertable (optional, needs TimescaleDB on the server).

    Converting moves all existing beliefs into time chunks.
    Writes to the table are blocked while that runs,
    so on a large database, plan a maintenance window.
    Running it again on a hypertable only (re)applies the compression setting.
    """
    try:
        version = timescaledb.ensure_extension(db.session)
    except timescaledb.TimescaleDBUnavailable as e:
        click.secho(str(e), **MsgStyle.ERROR)
        raise click.Abort()
    except DBAPIError as e:
        click.secho(
            f"Could not install the timescaledb extension: {e.orig}", **MsgStyle.ERROR
        )
        raise click.Abort()

    already_hypertable = timescaledb.is_hypertable(db.session)
    if not already_hypertable and not yes:
        if not click.confirm(
            f"This converts the {timescaledb.TABLE} table on {db.engine.url.render_as_string(hide_password=True)}"
            f" into a TimescaleDB {version} hypertable with chunks of {chunk_time_interval},"
            " blocking writes until done.\nDo you want to continue?"
        ):
            db.session.rollback()
            click.secho("I did nothing.", **MsgStyle.WARN)
            raise click.Abort()

    try:
        if already_hypertable:
            click.echo(
                f"{timescaledb.TABLE} is already a hypertable; leaving its chunks as they are."
            )
        else:
            timescaledb.convert_to_hypertable(db.session, chunk_time_interval)
        if compress_after is not None:
            timescaledb.enable_compression(db.session, compress_after)
            n_compressed = timescaledb.compress_eligible_chunks(
                db.session, compress_after
            )
            click.echo(
                f"Compressed {n_compressed} chunk(s) older than {compress_after}."
            )
        db.session.commit()
    except DBAPIError as e:
        db.session.rollback()
        click.secho(f"Nothing was changed: {e.orig}", **MsgStyle.ERROR)
        raise click.Abort()

    size = timescaledb.table_size(db.session)
    click.secho(
        f"{timescaledb.TABLE} is a hypertable (TimescaleDB {version}),"
        f" taking {size['table'] / 2**20:.0f} MiB of data and {size['indexes'] / 2**20:.0f} MiB of indexes.",
        **MsgStyle.SUCCESS,
    )


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
