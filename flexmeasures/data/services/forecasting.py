"""Forecasting job utilities."""

from __future__ import annotations

import logging

import click
from rq.timeouts import JobTimeoutException


FORECASTING_JOB_TIMEOUT_LOG_MESSAGE = (
    "Forecasting job timed out. To reduce runtime per job, decrease "
    "max-forecast-horizon or create more forecast cycles by setting "
    "forecast-frequency to a smaller timedelta (and retrain-frequency too, if it "
    "is larger). This splits the request into more, shorter jobs. Alternatively, "
    "increase FLEXMEASURES_JOB_TIMEOUT for the forecasting queue."
)


# TODO: we could also monitor the failed queue and re-enqueue jobs who had missing data
#       (and maybe failed less than three times so far)


def handle_forecasting_exception(job, exc_type, exc_value, traceback):
    """Persist forecasting job failure metadata.

    Forecasting failures stay attached to the original job instead of
    enqueueing a fallback job.
    """
    click.echo(
        "HANDLING RQ FORECASTING WORKER EXCEPTION: %s:%s\n" % (exc_type, exc_value)
    )

    if "failures" not in job.meta:
        job.meta["failures"] = 1
    else:
        job.meta["failures"] = job.meta["failures"] + 1
    job.save_meta()

    exception = {
        "type": exc_type.__name__ if exc_type is not None else None,
        "message": str(exc_value),
    }

    if isinstance(exc_type, type) and issubclass(exc_type, JobTimeoutException):
        logger = logging.getLogger(__name__)
        logger.warning(FORECASTING_JOB_TIMEOUT_LOG_MESSAGE)

    job.meta["exception"] = exception
    job.save_meta()
