"""Forecasting job utilities."""

from __future__ import annotations

import click


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

    job.meta["exception"] = {
        "type": exc_type.__name__ if exc_type is not None else None,
        "message": str(exc_value),
    }
    job.save_meta()
