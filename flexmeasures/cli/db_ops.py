"""CLI commands for saving, resetting, etc of the database"""

from datetime import datetime
import subprocess
from typing import NoReturn

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
    default=None,
    help="How much event time each chunk of the timed_belief table spans, as a PostgreSQL interval"
    f" [default when converting: {timescaledb.DEFAULT_CHUNK_TIME_INTERVAL}]."
    " On a hypertable already, this applies to chunks created from now on.",
)
@click.option(
    "--compress-after",
    default=None,
    help="Compress chunks whose events are all older than this PostgreSQL interval, now and from now on"
    f" [default when converting: {timescaledb.DEFAULT_COMPRESS_AFTER}]."
    " Compressed data still accepts writes, but more slowly."
    " On a hypertable already, this replaces the age set before.",
)
@click.option(
    "--force/--no-force",
    default=False,
    help="Skip the confirmation prompt, and convert on a play server, too.",
)
def enable_timescaledb(
    chunk_time_interval: str | None, compress_after: str | None, force: bool
):
    """Store time series data in a compressed TimescaleDB hypertable (optional, needs TimescaleDB on the server).

    Converting moves all existing beliefs into time chunks, and compresses the older ones.
    Writes to the table are blocked while that runs,
    so on a large database, plan a maintenance window.
    Running it again on a hypertable changes its chunk time interval (for new chunks) or its compression age.
    To go back to a plain table, use disable-timescaledb.
    """
    _check_mode(force)
    version = _install_timescaledb()
    table = timescaledb.TABLE
    already_hypertable = timescaledb.is_hypertable(db.session)
    if already_hypertable:
        if chunk_time_interval is None and compress_after is None:
            db.session.rollback()
            click.echo(
                f"{table} is already a hypertable."
                " Pass --chunk-time-interval or --compress-after to change its settings."
            )
            _report_timescaledb_size(version)
            return
        prompt = []
        if chunk_time_interval is not None:
            prompt.append(
                f"This makes chunks of the {table} hypertable created from now on span {chunk_time_interval}."
            )
        if compress_after is not None:
            policy_age = timescaledb.compression_policy_age(db.session)
            prompt.append(
                f"This compresses chunks of the {table} hypertable whose events are all older than {compress_after},"
                f" now and from now on (until now: {policy_age or 'none'})."
            )
    else:
        chunk_time_interval = (
            chunk_time_interval or timescaledb.DEFAULT_CHUNK_TIME_INTERVAL
        )
        compress_after = compress_after or timescaledb.DEFAULT_COMPRESS_AFTER
        prompt = [
            f"This converts the {table} table on {db.engine.url.render_as_string(hide_password=True)}"
            f" into a TimescaleDB {version} hypertable with chunks of {chunk_time_interval},"
            f" and compresses the chunks whose events are all older than {compress_after}, now and from now on."
            " Writes to the table are blocked until it is done.",
            "Going back takes `flexmeasures db-ops disable-timescaledb`, which copies all beliefs into a new table.",
        ]
    if compress_after is not None and not timescaledb.supports_compression(db.session):
        _abort(
            "This server runs the Apache-licensed edition of TimescaleDB, which cannot compress."
            " A hypertable without compression is slower than a plain table, and no smaller, so I did nothing."
        )
    if not force and not click.confirm(
        "\n".join(prompt + ["Do you want to continue?"])
    ):
        db.session.rollback()
        click.secho("I did nothing.", **MsgStyle.WARN)
        raise click.Abort()

    try:
        if not already_hypertable:
            timescaledb.convert_to_hypertable(db.session, chunk_time_interval)
        elif chunk_time_interval is not None:
            timescaledb.set_chunk_time_interval(db.session, chunk_time_interval)
            click.echo(
                f"Chunks created from now on span {chunk_time_interval}; existing chunks keep theirs."
            )
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
        _abort(f"Nothing was changed: {e.orig}")

    _report_timescaledb_size(version)


def _check_mode(force: bool):
    """Refuse to convert on a play server, unless forced.

    Simulations write into past periods and rerun over them,
    and writing into compressed periods is the slow case of a compressed hypertable.
    """
    if app.config.get("FLEXMEASURES_MODE") != "play":
        return
    message = (
        "This is a play server (FLEXMEASURES_MODE = 'play')."
        " Simulations write into past periods, which would be compressed,"
        " and writing into compressed data is slower (overwrites up to 2.6 times)."
    )
    if not force:
        _abort(f"{message} Use --force to convert anyway.")
    click.secho(message, **MsgStyle.WARN)


def _install_timescaledb() -> str:
    """Install the timescaledb extension if needed, warn if it sends usage data, and return its version."""
    try:
        version = timescaledb.ensure_extension(db.session)
    except timescaledb.TimescaleDBUnavailable as e:
        _abort(str(e))
    except DBAPIError as e:
        _abort(f"Could not install the timescaledb extension: {e.orig}")
    telemetry_level = timescaledb.setting(db.session, "timescaledb.telemetry_level")
    if telemetry_level not in (None, "off"):
        click.secho(
            f"TimescaleDB on this server sends usage data to Timescale (timescaledb.telemetry_level = {telemetry_level})."
            " To stop that, set timescaledb.telemetry_level = off in postgresql.conf.",
            **MsgStyle.WARN,
        )
    return version


def _abort(message: str) -> NoReturn:
    """Roll back whatever this command did so far, say why, and stop."""
    db.session.rollback()
    click.secho(message, **MsgStyle.ERROR)
    raise click.Abort()


@fm_db_ops.command("disable-timescaledb")
@with_appcontext
@click.option(
    "--force/--no-force",
    default=False,
    help="Skip the confirmation prompt.",
)
def disable_timescaledb(force: bool):
    """Store time series data in a plain table again, after enable-timescaledb.

    Copies all beliefs from the hypertable into a new plain timed_belief table, decompressing them on the way,
    and then drops the hypertable.
    Reads and writes of time series data wait until that is done,
    so on a large database, plan a maintenance window.
    Until the hypertable is dropped, the database needs room for both.
    The timescaledb extension stays installed.
    """
    from flexmeasures.data.utils import get_database_schema_revision_status

    table = timescaledb.TABLE
    if not timescaledb.is_hypertable(db.session):
        db.session.rollback()
        click.echo(f"{table} is not a hypertable, so there is nothing to undo.")
        return
    status = get_database_schema_revision_status(app)
    if status.current_heads and not status.is_migrated_to_head:
        _abort(
            f"The database is at revision {', '.join(status.current_heads)}, not at the latest one."
            f" The plain {table} table is created from the current data model, so run `flexmeasures db upgrade` first."
        )

    size = timescaledb.table_size(db.session)
    needed = timescaledb.decompressed_size(db.session)
    message = (
        f"This copies all beliefs in the {table} hypertable on {db.engine.url.render_as_string(hide_password=True)}"
        " into a new plain table, and then drops the hypertable."
        " Reads and writes of time series data wait until it is done."
        f" The copy needs about {needed / 2**20:.0f} MiB of disk space on the database server,"
        f" next to the {(size['table'] + size['indexes']) / 2**20:.0f} MiB the hypertable takes now."
    )
    if not force and not click.confirm(f"{message}\nDo you want to continue?"):
        db.session.rollback()
        click.secho("I did nothing.", **MsgStyle.WARN)
        raise click.Abort()
    if force:
        click.echo(message)

    try:
        n_copied = timescaledb.convert_to_plain_table(db.session)
        db.session.commit()
    except timescaledb.TimescaleDBUnavailable as e:
        _abort(f"Nothing was changed: {e}")
    except DBAPIError as e:
        _abort(f"Nothing was changed: {e.orig}")

    size = timescaledb.table_size(db.session)
    click.secho(
        f"{table} is a plain table again, holding {n_copied} beliefs"
        f" in {size['table'] / 2**20:.0f} MiB of data and {size['indexes'] / 2**20:.0f} MiB of indexes.",
        **MsgStyle.SUCCESS,
    )


def _report_timescaledb_size(version: str):
    """Say how much space the timed_belief hypertable takes."""
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
