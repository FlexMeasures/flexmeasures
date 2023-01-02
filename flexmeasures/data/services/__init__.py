from traceback import print_tb

import click


def handle_worker_exception(job, exc_type, exc_value, traceback):
    """
    Store exception as job meta data.
    """
    click.echo("XXXXXXXXXXXXXXXXXXXXXX")
    click.echo("HANDLING RQ WORKER EXCEPTION: %s:%s\n" % (exc_type, exc_value))
    print_tb(traceback)
    job.meta["exception"] = exc_value
    job.save_meta()
