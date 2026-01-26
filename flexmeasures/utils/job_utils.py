from __future__ import annotations

import os

from rq import Queue
from rq.job import Job


def work_on_rq(
    redis_queue: Queue, exc_handler=None, max_jobs=None, job: Job | str | None = None,
):

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

    if job:
        if isinstance(job, str):
            job = Job.fetch(job, connection=redis_queue.connection)
        worker.perform_job(job, redis_queue)
    else:
        worker.work(burst=True, max_jobs=max_jobs)
