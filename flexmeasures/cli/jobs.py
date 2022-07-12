from typing import List, Optional
import random
import string

import click
from flask import current_app as app
from flask.cli import with_appcontext
from rq import Queue, Worker
from sqlalchemy.orm import configure_mappers

from flexmeasures.data.services.forecasting import handle_forecasting_exception


@click.group("jobs")
def fm_jobs():
    """FlexMeasures: Job queueing."""


@fm_jobs.command("run-worker")
@with_appcontext
@click.option(
    "--name",
    default=None,
    required=False,
    help="Give your worker a recognizable name. Defaults to random string. Defaults to fm-worker-<randomstring>",
)
@click.option(
    "--queue",
    default=None,
    required=True,
    help="State which queue(s) to work on (using '|' as separator), e.g. 'forecasting', 'scheduling' or 'forecasting|scheduling'.",
)
def run_worker(queue: str, name: Optional[str]):
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

    worker = Worker(
        q_list,
        connection=connection,
        name=used_name,
        exception_handlers=[handle_forecasting_exception],
    )

    click.echo("\n=========================================================")
    click.echo(
        'Worker "%s" initialised: %s ― processing %s queue(s)'
        % (worker.name, worker, len(q_list))
    )
    for q in q_list:
        click.echo("Running against %s on %s" % (q, q.connection))
    click.echo("=========================================================\n")

    worker.work()


@fm_jobs.command("show-queues")
@with_appcontext
def show_queues():
    """
    Show the job queues and their job counts (including "failed" queue).

    To inspect contents, go to the RQ-Dashboard at <flexmeasures-URL>/tasks
    We use the app context to find out which redis queues to use.
    """

    configure_mappers()
    for q in list(app.queues.values()) + [
        Queue(connection=app.queues["forecasting"].connection, name="failed")
    ]:
        click.echo(f"Queue {q.name} has {q.count} jobs.")


@fm_jobs.command("clear-queue")
@with_appcontext
@click.option(
    "--queue",
    default=None,
    required=True,
    help="State which queue(s) to clear (using '|' as separator), e.g. 'forecasting', 'scheduling' or 'forecasting|scheduling'. 'failed' is also supported.",
)
def clear_queue(queue: str):
    """
    Clear a job queue.

    We use the app context to find out which redis queues to use.
    """

    q_list = parse_queue_list(queue, allow_failed=True)
    configure_mappers()
    for q in q_list:
        count_before = q.count
        q.empty()
        count_after = q.count
        click.echo(
            f"Cleared {count_before - count_after} jobs from {q}. Queue now contains {count_after} jobs."
        )


def parse_queue_list(queue_names_str: str, allow_failed: bool = False) -> List[Queue]:
    """Parse a | separated string of queue names against the app.queues dict.

    The app.queues dict is expected to have queue names as keys, and rq.Queue objects as values.

    :param queue_names_str: a string with queue names separated by the | character
    :returns:               a list of Queue objects.
    """
    q_list = []
    for q_name in queue_names_str.split("|"):
        if allow_failed and q_name == "failed":
            q_list.append(
                Queue(connection=app.queues["forecasting"].connection, name="failed")
            )
        elif q_name in app.queues:
            q_list.append(app.queues[q_name])
        else:
            raise ValueError(f"Unknown queue '{q_name}'.")
    return q_list


app.cli.add_command(fm_jobs)
