"""
CLI commands for controlling jobs
"""

from __future__ import annotations

import os
import random
import string

import click
from flask import current_app as app
from flask.cli import with_appcontext
from rq import Queue, Worker
from rq.job import Job
from rq.registry import FailedJobRegistry
from sqlalchemy.orm import configure_mappers
from tabulate import tabulate
import pandas as pd

from flexmeasures.data.services.scheduling import handle_scheduling_exception
from flexmeasures.data.services.forecasting import handle_forecasting_exception
from flexmeasures.cli.utils import MsgStyle


@click.group("jobs")
def fm_jobs():
    """FlexMeasures: Job queueing."""


@fm_jobs.command("run-worker")
@with_appcontext
@click.option(
    "--queue",
    default=None,
    required=True,
    help="State which queue(s) to work on (using '|' as separator), e.g. 'forecasting', 'scheduling' or 'forecasting|scheduling'.",
)
@click.option(
    "--name",
    default=None,
    required=False,
    help="Give your worker a recognizable name. Defaults to random string. Defaults to fm-worker-<randomstring>",
)
def run_worker(queue: str, name: str | None):
    """
    Start a worker process for forecasting and/or scheduling jobs.

    We use the app context to find out which redis queues to use.
    """

    q_list = parse_queue_list(queue)

    # https://stackoverflow.com/questions/50822822/high-sqlalchemy-initialization-overhead
    configure_mappers()

    connection = app.queues["forecasting"].connection

    # provide a random name if none was given
    if name is None:
        name = "fm-worker-" + "".join(random.sample(string.ascii_lowercase * 6, 6))
    worker_names = [w.name for w in Worker.all(connection=connection)]

    # making sure the name is unique
    used_name = name
    name_suffixes = iter(range(1, 51))
    while used_name in worker_names:
        used_name = f"{name}-{next(name_suffixes)}"

    error_handler = handle_worker_exception
    if queue == "scheduling":
        error_handler = handle_scheduling_exception
    elif queue == "forecasting":
        error_handler = handle_forecasting_exception
    worker = Worker(
        q_list,
        connection=connection,
        name=used_name,
        exception_handlers=[error_handler],
    )

    click.echo("\n=========================================================")
    click.secho(
        'Worker "%s" initialised: %s ― processing %s queue(s)'
        % (worker.name, worker, len(q_list)),
        **MsgStyle.SUCCESS,
    )
    for q in q_list:
        click.echo("Running against %s on %s" % (q, q.connection))
    click.echo("=========================================================\n")

    worker.work()


@fm_jobs.command("show-queues")
@with_appcontext
def show_queues():
    """
    Show the job queues and their job counts (including the "failed" registry).

    To inspect contents, go to the RQ-Dashboard at <flexmeasures-URL>/tasks
    We use the app context to find out which redis queues to use.
    """

    configure_mappers()
    queue_data = [
        (
            q.name,
            q.started_job_registry.count,
            q.count,
            q.deferred_job_registry.count,
            q.scheduled_job_registry.count,
            q.failed_job_registry.count,
        )
        for q in app.queues.values()
    ]
    click.echo(
        tabulate(
            queue_data,
            headers=["Queue", "Started", "Queued", "Deferred", "Scheduled", "Failed"],
        )
    )


@fm_jobs.command("save-last-failed")
@with_appcontext
@click.option(
    "--n",
    type=int,
    default=10,
    help="The number of last jobs to save.",
)
@click.option(
    "--queue",
    "queue_name",
    type=str,
    default="scheduling",
    help="The queue to look in.",
)
@click.option(
    "--file",
    type=click.Path(),
    default="failed_jobs.csv",
    help="The CSV file to save the failed jobs.",
)
def save_last_failed(n: int, queue_name: str, file: str):
    """
    Save the last n failed jobs (10 by default) to a file.
    """
    available_queues = app.queues
    if queue_name not in available_queues.keys():
        click.secho(
            f"Unknown queue '{queue_name}'. Available queues: {available_queues.keys()}",
            **MsgStyle.ERROR,
        )
        raise click.Abort()
    else:
        queue = available_queues[queue_name]

    registry = FailedJobRegistry(queue=queue)
    job_ids = registry.get_job_ids()[-n:]
    failed_jobs = []

    for job_id in job_ids:
        try:
            job = Job.fetch(job_id, connection=queue.connection)
            kwargs = job.kwargs or {}
            asset_info = kwargs.get("asset_or_sensor", {})

            failed_jobs.append(
                {
                    "Job ID": job.id,
                    "ID": asset_info.get("id", "N/A"),
                    "Class": asset_info.get("class", "N/A"),
                    "Error": job.exc_info,
                    "All kwargs": kwargs,
                    "Function name": getattr(job, "func_name", "N/A"),
                    "Started at": getattr(job, "started_at", "N/A"),
                    "Ended at": getattr(job, "ended_at", "N/A"),
                }
            )
        except Exception as e:
            click.secho(
                f"Job {job_id} failed to fetch with error: {str(e)}", fg="yellow"
            )

    if failed_jobs:
        if os.path.exists(file):
            if not click.confirm(f"{file} already exists. Overwrite?", default=False):
                new_file = click.prompt(
                    "Enter a new filename (must end with .csv)", type=str
                )
                while not new_file.lower().endswith(".csv"):
                    click.secho("Invalid filename. It must end with .csv.", fg="red")
                    new_file = click.prompt(
                        "Enter a new filename (must end with .csv)", type=str
                    )
                file = new_file

        # Save the failed jobs to a CSV file
        pd.DataFrame(failed_jobs).to_csv(file, index=False)
        click.secho(f"Saved {len(failed_jobs)} failed jobs to {file}.", fg="green")
    else:
        click.secho("No failed jobs found.", fg="yellow")


@fm_jobs.command("clear-queue")
@with_appcontext
@click.option(
    "--queue",
    default=None,
    required=True,
    help="State which queue(s) to clear (using '|' as separator), e.g. 'forecasting', 'scheduling' or 'forecasting|scheduling'.",
)
@click.option(
    "--deferred",
    is_flag=True,
    default=False,
    help="If True, the deferred registry of the queue(s) will be cleared (and not the jobs currently in queue to be done).",
)
@click.option(
    "--scheduled",
    is_flag=True,
    default=False,
    help="If True, the scheduled registry of the queue(s) will be cleared (and not the jobs currently in queue to be done).",
)
@click.option(
    "--failed",
    is_flag=True,
    default=False,
    help="If True, the failed registry of the queue(s) will be cleared (and not the jobs currently in queue to be done).",
)
def clear_queue(queue: str, deferred: bool, scheduled: bool, failed: bool):
    """
    Clear a job queue (or its registry of deferred/scheduled/failed jobs).

    We use the app context to find out which redis queues to use.
    """
    q_list = parse_queue_list(queue)
    registries = dict(
        deferred=("deferred_job_registry", deferred),
        scheduled=("scheduled_job_registry", scheduled),
        failed=("failed_job_registry", failed),
    )
    configure_mappers()
    for the_queue in q_list:
        for _type, (registry, needs_clearing) in registries.items():
            if needs_clearing:
                reg = getattr(the_queue, registry)
                count_before = reg.count
                for job_id in reg.get_job_ids():
                    reg.remove(job_id)  # not actually deleting the job
                count_after = reg.count
                click.secho(
                    f"Cleared {count_before - count_after} {_type} jobs from the {registry} at {the_queue}.",
                    **MsgStyle.WARN,
                )
                wrap_up_message(count_after)
        if not any([deferred, scheduled, failed]):
            count_before = the_queue.count
            if count_before > 0:
                the_queue.empty()
            count_after = the_queue.count
            click.secho(
                f"Cleared {count_before - count_after} jobs from {the_queue}.",
                **MsgStyle.SUCCESS,
            )
            wrap_up_message(count_after)


@fm_jobs.command("delete-queue")
@with_appcontext
@click.option(
    "--queue",
    default=None,
    required=True,
    help="State which queue to delete.",
)
def delete_queue(queue: str):
    """
    Delete a job queue.
    """
    if not app.redis_connection.sismember("rq:queues", f"rq:queue:{queue}"):
        click.secho(
            f"Queue '{queue}' does not exist.",
            **MsgStyle.ERROR,
        )
        raise click.Abort()
    success = app.redis_connection.srem("rq:queues", f"rq:queue:{queue}")
    if success:
        click.secho(
            f"Queue '{queue}' removed.",
            **MsgStyle.SUCCESS,
        )
    else:
        click.secho(
            f"Failed to remove queue '{queue}'.",
            **MsgStyle.ERROR,
        )
        raise click.Abort()


def wrap_up_message(count_after: int):
    if count_after > 0:
        click.secho(
            f"There are {count_after} jobs which could not be removed for some reason.",
            **MsgStyle.WARN,
        )
    else:
        click.echo("No jobs left.")


def handle_worker_exception(job, exc_type, exc_value, traceback):
    """
    Just a fallback, usually we would use the per-queue handler.
    """
    queue_name = job.origin
    click.echo(f"HANDLING RQ {queue_name.upper()} EXCEPTION: {exc_type}: {exc_value}")
    job.meta["exception"] = exc_value
    job.save_meta()


def parse_queue_list(queue_names_str: str) -> list[Queue]:
    """Parse a | separated string of queue names against the app.queues dict.

    The app.queues dict is expected to have queue names as keys, and rq.Queue objects as values.

    :param queue_names_str: a string with queue names separated by the | character
    :returns:               a list of Queue objects.
    """
    q_list = []
    for q_name in queue_names_str.split("|"):
        if q_name in app.queues:
            q_list.append(app.queues[q_name])
        else:
            raise ValueError(f"Unknown queue '{q_name}'.")
    return q_list


app.cli.add_command(fm_jobs)
