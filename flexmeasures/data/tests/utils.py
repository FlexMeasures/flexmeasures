import os

import click


def work_on_rq(redis_queue, exc_handler=None, max_jobs=None):

    #  we only want this import distinction to matter when we actually are testing
    if os.name == "nt":
        from rq_win import WindowsWorker as SimpleWorker
    else:
        from rq import SimpleWorker

    exc_handlers = []
    if exc_handler is not None:
        exc_handlers.append(exc_handler)
    print("STARTING SIMPLE RQ WORKER, seeing %d job(s)" % redis_queue.count)
    worker = SimpleWorker(
        [redis_queue],
        connection=redis_queue.connection,
        exception_handlers=exc_handlers,
    )
    worker.work(burst=True, max_jobs=max_jobs)


def exception_reporter(job, exc_type, exc_value, traceback):
    click.echo("HANDLING RQ WORKER EXCEPTION: %s:%s\n" % (exc_type, exc_value))
