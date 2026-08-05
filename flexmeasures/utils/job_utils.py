from __future__ import annotations

from datetime import timedelta
import os
import logging
from collections.abc import Mapping
from typing import Any

import isodate  # type: ignore[import-untyped]
from flask import current_app, has_app_context
from rq import Queue
from rq.job import Job

RQ_DEFAULT_JOB_TIMEOUT = 180
KNOWN_JOB_QUEUES = frozenset(("forecasting", "scheduling", "ingestion"))


def _timeout_to_seconds(timeout: timedelta | str) -> int:
    """Convert a configured timeout value to whole seconds for RQ."""
    if isinstance(timeout, str):
        try:
            timeout = isodate.parse_duration(timeout)
        except isodate.ISO8601Error as exc:
            raise ValueError(
                f"Job timeout {timeout!r} is not a valid ISO 8601 duration."
            ) from exc

    if isinstance(timeout, isodate.Duration):
        raise ValueError(
            "Job timeouts must be fixed durations without years or months."
        )

    if isinstance(timeout, timedelta):
        seconds = timeout.total_seconds()
    else:
        raise TypeError(
            f"Job timeout values must be ISO 8601 strings or timedeltas, not {type(timeout).__name__}."
        )

    if seconds <= 0:
        raise ValueError("Job timeouts must be positive.")
    if not seconds.is_integer():
        raise ValueError("Job timeouts must resolve to whole seconds.")
    return int(seconds)


def _configured_default_job_timeout(
    config: Mapping[str, Any], logger: logging.Logger
) -> int:
    timeout = config.get(
        "FLEXMEASURES_DEFAULT_JOB_TIMEOUT",
        timedelta(seconds=RQ_DEFAULT_JOB_TIMEOUT),
    )
    try:
        return _timeout_to_seconds(timeout)
    except (TypeError, ValueError) as exc:
        logger.error(
            "Invalid FLEXMEASURES_DEFAULT_JOB_TIMEOUT %r: %s. Falling back to RQ's default of %s seconds.",
            timeout,
            exc,
            RQ_DEFAULT_JOB_TIMEOUT,
        )
        return RQ_DEFAULT_JOB_TIMEOUT


def get_job_timeout(
    queue_name: str,
    config: Mapping[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> int:
    """Return the configured RQ timeout for jobs in ``queue_name``."""
    if config is None:
        config = current_app.config
    if logger is None:
        logger = (
            current_app.logger if has_app_context() else logging.getLogger(__name__)
        )

    queue_timeouts = config.get("FLEXMEASURES_JOB_TIMEOUT", {})
    if not isinstance(queue_timeouts, Mapping):
        logger.error(
            "Invalid FLEXMEASURES_JOB_TIMEOUT %r: expected a mapping of queue names to timeouts. Falling back to FLEXMEASURES_DEFAULT_JOB_TIMEOUT.",
            queue_timeouts,
        )
        return _configured_default_job_timeout(config, logger)

    unknown_queue_names = sorted(
        str(configured_queue_name)
        for configured_queue_name in queue_timeouts
        if configured_queue_name not in KNOWN_JOB_QUEUES
    )
    if unknown_queue_names:
        logger.error(
            "Invalid FLEXMEASURES_JOB_TIMEOUT queue names %s. Expected queue names are %s.",
            unknown_queue_names,
            sorted(KNOWN_JOB_QUEUES),
        )

    if queue_name not in queue_timeouts:
        return _configured_default_job_timeout(config, logger)

    timeout = queue_timeouts[queue_name]
    try:
        return _timeout_to_seconds(timeout)
    except (TypeError, ValueError) as exc:
        logger.error(
            "Invalid FLEXMEASURES_JOB_TIMEOUT for queue %r (%r): %s. Falling back to FLEXMEASURES_DEFAULT_JOB_TIMEOUT.",
            queue_name,
            timeout,
            exc,
        )
        return _configured_default_job_timeout(config, logger)


def work_on_rq(
    redis_queue: Queue,
    exc_handler=None,
    max_jobs=None,
    job: Job | str | None = None,
):

    #  we only want this import distinction to matter when we actually are testing
    if os.name == "nt":
        from rq_win import WindowsWorker as SimpleWorker  # type: ignore[import-untyped]
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
