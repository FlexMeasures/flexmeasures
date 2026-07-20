"""Forecasting job utilities."""

from __future__ import annotations

import logging

import click
from rq.timeouts import JobTimeoutException


FORECASTING_JOB_TIMEOUT_HINT = (
    "Forecasting job timed out. "
    "Decrease max-forecast-horizon to reduce runtime per job. "
    "To create more forecast cycles, set forecast-frequency to a smaller timedelta. "
    "If retrain-frequency is larger, decrease it too. "
    "More cycles split the request into more, shorter jobs."
)
FORECASTING_JOB_TIMEOUT_HOST_HINT = "Alternatively, hosts can increase FLEXMEASURES_JOB_TIMEOUT for the forecasting queue."


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
        logger.warning(
            "%s %s",
            FORECASTING_JOB_TIMEOUT_HINT,
            FORECASTING_JOB_TIMEOUT_HOST_HINT,
        )
        exception["hint"] = FORECASTING_JOB_TIMEOUT_HINT

    job.meta["exception"] = exception
    job.save_meta()
