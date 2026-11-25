"""Every queue stores why a job failed in the same shape, and every reader renders it the same way."""

import pytest
from rq.job import Job

from flexmeasures.data.services.utils import failed_job_reason, job_status_description
from flexmeasures.utils.job_utils import work_on_rq


@pytest.mark.parametrize(
    "queue_name", ["scheduling", "forecasting", "reporting", "ingestion"]
)
def test_a_failed_job_says_why_on_every_queue(app, clean_redis, queue_name):
    """A job failing on any queue, with that queue's own exception handler, reads as the exception's type and message.

    Before every queue stored the same summary, a forecasting job read ``dict: {...}``,
    a report or plugin automation read ``str: ...``, and a schedule stored the exception itself.
    """
    from flexmeasures.cli.jobs import get_exception_handler

    queue = app.queues[queue_name]
    try:
        job = queue.enqueue("math.sqrt", -1)
        work_on_rq(queue, exc_handler=get_exception_handler(queue_name), job=job)

        fetched = Job.fetch(job.id, connection=queue.connection)
        assert fetched.is_failed
        assert fetched.meta["exception"] == {
            "type": "ValueError",
            "message": "math domain error",
        }
        assert failed_job_reason(fetched) == "ValueError: math domain error"
        assert job_status_description(fetched).endswith(
            "job failed with ValueError: math domain error."
        )
    finally:
        # Leave no failed job behind, which clean_redis cannot fetch again on the next run.
        app.redis_connection.flushdb()
