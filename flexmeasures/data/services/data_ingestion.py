"""
Logic around data ingestion (jobs)
"""

from __future__ import annotations

from flask import current_app
from rq.job import Job
import timely_beliefs as tb

from flexmeasures.data import db
from flexmeasures.data.utils import save_to_db


def add_beliefs_to_database(
    data: tb.BeliefsDataFrame | list[tb.BeliefsDataFrame],
    forecasting_jobs: list[Job] | None = None,
    save_changed_beliefs_only: bool = True,
) -> str:
    """Save sensor data to the database and optionally enqueue forecasting jobs.

    This function is intended to be called as an RQ job by an ingestion queue worker,
    but can also be called directly (e.g. as a fallback when no workers are available).

    :param data:                        BeliefsDataFrame (or list thereof) to be saved.
    :param forecasting_jobs:            Optional list of forecasting Jobs to enqueue after saving.
    :param save_changed_beliefs_only:   If True, skip saving beliefs whose value hasn't changed.
    :returns:                           Status string, one of:
                                        - 'success'
                                        - 'success_with_unchanged_beliefs_skipped'
                                        - 'success_but_nothing_new'
    """
    status = save_to_db(data, save_changed_beliefs_only=save_changed_beliefs_only)
    db.session.commit()

    # Only enqueue forecasting jobs upon successfully saving new data
    if status[:7] == "success" and status != "success_but_nothing_new":
        if forecasting_jobs is not None:
            for job in forecasting_jobs:
                current_app.queues["forecasting"].enqueue_job(job)

    return status
