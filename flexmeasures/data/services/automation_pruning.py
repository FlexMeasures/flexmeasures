"""Delete the records of automation runs that are older than their time-to-live, so that the run tables stop growing.

Deleting a run deletes its attempts and its jobs, too (their foreign keys cascade).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import and_, delete, exists, false, not_, or_, select, tuple_
from sqlalchemy.orm import aliased

from flexmeasures.data import db
from flexmeasures.data.models.automations import Automation, AutomationRun
from flexmeasures.data.services.automation_monitoring import (
    unalerted_failure_criterion,
)
from flexmeasures.utils.time_utils import server_now

# Pruning runs at most this often, however often `flexmeasures jobs run-automations` runs.
AUTOMATION_RUN_PRUNING_INTERVAL = timedelta(hours=1)
AUTOMATION_RUN_PRUNING_REDIS_KEY = "flexmeasures:automation-run-pruning"
# Stands for the TTL setting in the app config, as None means keeping runs forever.
FROM_CONFIG = object()


def _expired(
    ttl_setting: dict[str, timedelta | None] | timedelta | None, now: datetime
):
    """Return the criterion for a run scheduled longer ago than the time-to-live of its automation type.

    :param ttl_setting: FLEXMEASURES_AUTOMATION_DBLOGS_TTL:
                        a timedelta for all types, or a timedelta per type, with "default" for types not named.
                        None keeps runs forever, whether for all types or for one type.
    """
    if ttl_setting is None:
        return false()
    if isinstance(ttl_setting, timedelta):
        return AutomationRun.scheduled_at < now - ttl_setting
    named_types = [
        automation_type
        for automation_type in ttl_setting
        if automation_type != "default"
    ]
    criteria = [
        and_(
            AutomationRun.automation_type == automation_type,
            AutomationRun.scheduled_at < now - ttl_setting[automation_type],
        )
        for automation_type in named_types
        if ttl_setting[automation_type] is not None
    ]
    if ttl_setting.get("default") is not None:
        criteria.append(
            and_(
                AutomationRun.automation_type.notin_(named_types),
                AutomationRun.scheduled_at < now - ttl_setting["default"],
            )
        )
    return or_(*criteria) if criteria else false()


def prunable_automation_runs_criterion(
    ttl_setting: dict[str, timedelta | None] | timedelta | None,
    stuck_after: timedelta,
    now: datetime,
):
    """Return the criterion for a run whose record may be deleted.

    That is a run scheduled longer ago than the time-to-live of its automation type, except:

    - a run that a runner holds a live claim on, as it is being dispatched;
    - the latest run of its automation, so that every automation that ever ran still shows how it last went;
    - a failure of a monitored automation that `flexmeasures monitor automations` did not report yet.

    A run that never finished, because the worker running its job died for instance, is deleted once it expired, too:
    by then nothing will finish it any more.
    """
    newer_run = aliased(AutomationRun)
    return and_(
        _expired(ttl_setting, now),
        or_(
            AutomationRun.claim_owner.is_(None),
            AutomationRun.claim_expires_at.is_(None),
            AutomationRun.claim_expires_at <= now,
        ),
        exists().where(
            newer_run.automation_id == AutomationRun.automation_id,
            tuple_(newer_run.scheduled_at, newer_run.id)
            > tuple_(AutomationRun.scheduled_at, AutomationRun.id),
        ),
        not_(
            and_(
                AutomationRun.automation.has(Automation.monitored.is_(True)),
                unalerted_failure_criterion(stuck_after, now),
            )
        ),
    )


def prune_automation_runs(
    now: datetime | None = None,
    ttl_setting: dict[str, timedelta | None] | timedelta | None | object = FROM_CONFIG,
    stuck_after: timedelta | None = None,
    batch_size: int = 1000,
    time_budget: timedelta = timedelta(seconds=30),
) -> int:
    """Delete the records of the runs that outlived their time-to-live, and return how many were deleted.

    Runs are deleted in batches, each in a transaction of its own, so that no table is locked for long.
    Once the time budget is spent, no new batch starts, and whatever is left waits for the next pruning.

    :param now:         The moment to judge by, which defaults to the server's current time.
    :param ttl_setting: FLEXMEASURES_AUTOMATION_DBLOGS_TTL (read from the app config if not given), where None keeps all runs.
    :param stuck_after: FLEXMEASURES_MONITOR_AUTOMATIONS_STUCK_AFTER (read from the app config if not given).
    :param batch_size:  How many runs to delete per transaction.
    :param time_budget: How long to keep starting new batches.
    """
    if now is None:
        now = server_now()
    now = now.astimezone(timezone.utc)
    if ttl_setting is FROM_CONFIG:
        ttl_setting = current_app.config.get("FLEXMEASURES_AUTOMATION_DBLOGS_TTL")
    if stuck_after is None:
        stuck_after = current_app.config["FLEXMEASURES_MONITOR_AUTOMATIONS_STUCK_AFTER"]
    criterion = prunable_automation_runs_criterion(ttl_setting, stuck_after, now)
    deadline = time.monotonic() + time_budget.total_seconds()
    n_deleted = 0
    while True:
        run_ids = db.session.scalars(
            select(AutomationRun.id).where(criterion).limit(batch_size)
        ).all()
        if run_ids:
            db.session.execute(
                delete(AutomationRun)
                .where(AutomationRun.id.in_(run_ids))
                .execution_options(synchronize_session=False)
            )
        db.session.commit()
        n_deleted += len(run_ids)
        if len(run_ids) < batch_size or time.monotonic() >= deadline:
            return n_deleted


def prune_automation_runs_if_due(now: datetime | None = None) -> int | None:
    """Prune the automation runs, unless they were pruned less than an hour ago.

    Redis keeps track of the last pruning, so that runners on several machines prune once an hour between them.
    Return how many runs were deleted, or None if pruning was not due.
    """
    if now is None:
        now = server_now()
    due = current_app.redis_connection.set(
        AUTOMATION_RUN_PRUNING_REDIS_KEY,
        now.isoformat(),
        nx=True,
        ex=int(AUTOMATION_RUN_PRUNING_INTERVAL.total_seconds()),
    )
    if not due:
        return None
    return prune_automation_runs(now)
