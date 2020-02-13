import click
from flask import current_app as app
from rq import Worker
from sqlalchemy.orm import configure_mappers

from bvp.data.services.forecasting import handle_forecasting_exception


@app.cli.command("run_worker")
@click.option(
    "--name",
    default=None,
    help="Give your worker a recognizable name. Defaults to random string.",
)
@click.option(
    "--queue",
    default=None,
    help="State which queue(s) to work on (using '|' as separator), e.g. 'forecasting', 'scheduling' or 'forecasting|scheduling'.",
)
def run_worker(name: str, queue: str):
    """
    Use this CLI task to let a worker process forecasting and/or scheduling jobs.
    It uses the app context to find out which redis queues to use.
    """

    q_list = []
    for q_name in queue.split("|"):
        if q_name in app.queues:
            q_list.append(app.queues[q_name])
        else:
            raise ValueError(f"Unknown queue '{q_name}'.")

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
