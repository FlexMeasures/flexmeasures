"""Forecasting job utilities."""

from __future__ import annotations

from datetime import datetime

import click


# TODO: we could also monitor the failed queue and re-enqueue jobs who had missing data
#       (and maybe failed less than three times so far)


def handle_forecasting_exception(job, exc_type, exc_value, traceback):
    """Persist forecasting job failure metadata without queueing a legacy fallback."""
    click.echo(
        "HANDLING RQ FORECASTING WORKER EXCEPTION: %s:%s\n" % (exc_type, exc_value)
    )

    if "failures" not in job.meta:
        job.meta["failures"] = 1
    else:
        job.meta["failures"] = job.meta["failures"] + 1
    job.save_meta()

    job.meta["exception"] = exc_value
    if isinstance(job.meta.get("start"), datetime):
        job.meta["start"] = job.meta["start"].isoformat()
    if isinstance(job.meta.get("end"), datetime):
        job.meta["end"] = job.meta["end"].isoformat()
    job.save_meta()

    # The fixed-viewpoint pipeline is the only supported forecasting path, so
    # failed jobs stay failed until a user retries with an updated request.
    return False
