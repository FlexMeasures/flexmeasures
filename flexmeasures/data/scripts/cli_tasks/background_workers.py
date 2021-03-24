from typing import List

import click
from flask import current_app as app
from rq import Queue, Worker
from sqlalchemy.orm import configure_mappers

from flexmeasures.data.services.forecasting import handle_forecasting_exception


@app.cli.command("run-worker")
@click.option(
    "--name",
    default=None,
    required=True,
    help="Give your worker a recognizable name. Defaults to random string.",
)
@click.option(
    "--queue",
    default=None,
    required=True,
    help="State which queue(s) to work on (using '|' as separator), e.g. 'forecasting', 'scheduling' or 'forecasting|scheduling'.",
)
def run_worker(name: str, queue: str):
    """
    Use this CLI task to let a worker process forecasting and/or scheduling jobs.
    It uses the app context to find out which redis queues to use.
    """

    q_list = parse_queue_list(queue)

    # https://stackoverflow.com/questions/50822822/high-sqlalchemy-initialization-overhead
    configure_mappers()

    worker = Worker(
        q_list,
        connection=app.queues["forecasting"].connection,
        name=name,
        exception_handlers=[handle_forecasting_exception],
    )

    click.echo("\n=========================================================")
    click.echo(
        'Worker "%s" initialised: %s (processing %s queues)'
        % (worker.name, worker, len(q_list))
    )
    for q in q_list:
        click.echo("Running against %s on %s" % (q, q.connection))
    click.echo("=========================================================\n")

    worker.work()


@app.cli.command("clear-queue")
@click.option(
    "--queue",
    default=None,
    required=True,
    help="State which queue(s) to clear (using '|' as separator), e.g. 'forecasting', 'scheduling' or 'forecasting|scheduling'.",
)
def clear_queue(queue: str):
    """
    Use this CLI task to clear a queue.
    It uses the app context to find out which redis queues to use.
    """

    q_list = parse_queue_list(queue)
    configure_mappers()
    for q in q_list:
        count_before = q.count
        q.empty()
        count_after = q.count
        click.echo(
            f"Cleared {count_before - count_after} jobs from {q}. Queue now contains {count_after} jobs."
        )


def parse_queue_list(queue_names_str: str) -> List[Queue]:
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
