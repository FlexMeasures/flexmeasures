"""Logic for deciding whether (and up to when) the materialized view caching the most
recent beliefs can be trusted, based on when it was last refreshed.

The `flexmeasures db-ops refresh-materialized-views` CLI command records its last successful
run in the latest_task_run table, making that timestamp the single source of truth on the
view's freshness (hosts control the cadence solely via how they schedule that command).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import current_app

from flexmeasures.data import db
from flexmeasures.data.models.task_runs import LatestTaskRun

MVIEW_REFRESH_TASK_NAME = "refresh-materialized-views"

# How far before the recorded refresh time to place the cutoff.
# The recorded time marks the refresh's completion, while REFRESH MATERIALIZED VIEW
# takes its snapshot of the beliefs table when it starts, so the margin should
# comfortably exceed the duration of a refresh.
MVIEW_CUTOFF_SAFETY_MARGIN = timedelta(minutes=15)

# If the last successful refresh is older than this, assume the host's periodic refresh
# is broken and stop trusting the view altogether (queries fall back to the beliefs table).
MAX_MVIEW_AGE = timedelta(hours=24)


def get_mview_cutoff() -> datetime | None:
    """Return the datetime before which events can be looked up in the materialized view.

    Returns None if the view should not be used at all: no successful refresh has been
    recorded (yet), or the last one is older than MAX_MVIEW_AGE.
    """
    task_run = db.session.get(LatestTaskRun, MVIEW_REFRESH_TASK_NAME)
    if task_run is None or not task_run.status:
        return None
    if task_run.datetime < datetime.now(timezone.utc) - MAX_MVIEW_AGE:
        current_app.logger.warning(
            f"The materialized view was last refreshed at {task_run.datetime} (more than {MAX_MVIEW_AGE} ago)."
            f" Falling back to querying the beliefs table."
            f" Is the '{MVIEW_REFRESH_TASK_NAME}' cron job still running?"
        )
        return None
    return task_run.datetime - MVIEW_CUTOFF_SAFETY_MARGIN
