"""CLI commands for saving, resetting, etc of the database"""

from datetime import datetime
import subprocess

from flask import current_app as app
from flask.cli import with_appcontext
import flask_migrate as migrate
import click

from flexmeasures.cli.utils import MsgStyle
from flexmeasures.data import db


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
    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    db_host_and_db_name = db_uri.split("@")[-1]
    click.echo(f"Backing up {db_host_and_db_name} database")
    db_name = db_host_and_db_name.split("/")[-1]
    time_of_saving = datetime.now().strftime("%F-%H%M")
    dump_filename = f"pgbackup_{db_name}_{time_of_saving}.dump"
    command_for_dumping = f"pg_dump --no-privileges --no-owner --data-only --format=c --file={dump_filename} '{db_uri}'"
    try:
        subprocess.check_output(command_for_dumping, shell=True)
        click.secho(f"db dump successful: saved to {dump_filename}", **MsgStyle.SUCCESS)

    except Exception as e:
        click.secho(f"Exception happened during dump: {e}", **MsgStyle.ERROR)
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

    db_uri: str = app.config.get("SQLALCHEMY_DATABASE_URI")  # type: ignore
    db_host_and_db_name = db_uri.split("@")[-1]
    click.echo(f"Restoring {db_host_and_db_name} database from file {file}")
    command_for_restoring = f"pg_restore -d {db_uri} {file}"
    try:
        subprocess.check_output(command_for_restoring, shell=True)
        click.secho("db restore successful", **MsgStyle.SUCCESS)

    except Exception as e:
        click.secho(f"Exception happened during restore: {e}", **MsgStyle.ERROR)
        click.secho("db restore unsuccessful", **MsgStyle.ERROR)


@fm_db_ops.command("refresh-materialized-views")
@with_appcontext
@click.option(
    "--concurrent",
    is_flag=True,
    default=False,
    help="Refresh without locking reads on the materialized view, at the cost of higher resource usage."
    " Requires the unique index created by the corresponding migration.",
)
def refresh_materialized_views(concurrent: bool):
    """
    Refresh the materialized view that caches the most recent beliefs (for faster queries).

    By default, this locks the materialized view for the duration of the refresh.
    Use the --concurrent option to avoid locking reads, at the cost of higher resource usage
    (this requires the unique index that the corresponding migration created).

    Run this periodically (e.g. from a cron job) to bound how stale the cached data can get.
    The time of the last successful run is recorded in the latest_task_run table, which serves
    as the queries' cutoff between trusting the view and reading recent events from the beliefs
    table, and can be monitored with ``flexmeasures monitor latest-run``.
    """
    import time

    from sqlalchemy import text
    from timely_beliefs.beliefs.materialized_views import refresh_mview_ddl

    from flexmeasures.data.transactional import task_with_status_report
    from flexmeasures.data.models.task_runs import LatestTaskRun
    from flexmeasures.data.services.materialized_views import MVIEW_REFRESH_TASK_NAME

    @task_with_status_report(MVIEW_REFRESH_TASK_NAME)
    def _refresh():
        ddl = refresh_mview_ddl(concurrently=concurrent)
        if concurrent:
            # REFRESH MATERIALIZED VIEW CONCURRENTLY cannot run inside a transaction block
            with db.engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as connection:
                connection.execute(text(ddl))
        else:
            db.session.execute(text(ddl))

    start_time = time.time()
    click.secho(
        f"Refreshing materialized view{' concurrently' if concurrent else ''}...",
        **MsgStyle.WARN,
    )
    _refresh()

    # The task decorator recorded success/failure in the db; convey it as an exit status, too
    task_run = db.session.get(LatestTaskRun, MVIEW_REFRESH_TASK_NAME)
    if task_run is None or not task_run.status:
        click.secho("Refreshing the materialized view failed.", **MsgStyle.ERROR)
        raise click.Abort()
    click.secho(
        f"Materialized view refreshed in {time.time() - start_time:.2f} seconds.",
        **MsgStyle.SUCCESS,
    )


app.cli.add_command(fm_db_ops)
