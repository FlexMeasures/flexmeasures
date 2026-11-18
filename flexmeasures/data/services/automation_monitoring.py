"""Find the automation runs that failed, so that monitoring can report them."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, not_, or_, select
from sqlalchemy.orm import selectinload

from flexmeasures.data import db
from flexmeasures.data.models.automations import Automation, AutomationRun
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.services.automations import AUTOMATION_RUN_MAX_DISPATCH_ATTEMPTS
from flexmeasures.utils.time_utils import server_now

EXECUTION_FAILED = "execution failed"
STUCK = "stuck"
DISPATCH_FAILED = "dispatch failed"


@dataclass(frozen=True)
class FailedAutomationRun:
    """An automation run that failed, with the way it failed."""

    run: AutomationRun
    reason: str


@dataclass
class AutomationFailures:
    """The failed runs of one automation, collapsed into what a digest says about them."""

    automation: Automation
    failed_runs: list[FailedAutomationRun] = field(default_factory=list)

    @property
    def reason_counts(self) -> Counter:
        """How many runs failed in each way."""
        return Counter(failed_run.reason for failed_run in self.failed_runs)

    @property
    def last_run(self) -> AutomationRun:
        """The failed run that was due most recently."""
        return max(
            (failed_run.run for failed_run in self.failed_runs),
            key=lambda run: (run.scheduled_at, run.id),
        )

    @property
    def last_error(self) -> str | None:
        """The error of the most recent failed run that recorded one, if any did."""
        runs_with_an_error = [
            failed_run.run
            for failed_run in self.failed_runs
            if failed_run.run.last_error_type or failed_run.run.last_error_message
        ]
        if not runs_with_an_error:
            return None
        run = max(runs_with_an_error, key=lambda run: (run.scheduled_at, run.id))
        return ": ".join(
            part for part in (run.last_error_type, run.last_error_message) if part
        )


def _dispatch_failed_for_good(now: datetime):
    """Return the criterion for a run whose dispatch did not finish and will not be attempted again.

    No runner may hold a live claim on it, or it is still being dispatched.
    Only a forecast run is dispatched again, until its attempts are used up (see `get_dispatchable_automation_runs`),
    so a run of any other type has failed for good after its first attempt.
    """
    return and_(
        AutomationRun.dispatch_completed_at.is_(None),
        or_(
            AutomationRun.claim_owner.is_(None),
            AutomationRun.claim_expires_at.is_(None),
            AutomationRun.claim_expires_at <= now,
        ),
        not_(
            and_(
                AutomationRun.automation_type == "forecasting",
                AutomationRun.attempt_count < AUTOMATION_RUN_MAX_DISPATCH_ATTEMPTS,
            )
        ),
    )


def get_unalerted_failed_automation_runs(
    stuck_after: timedelta,
    now: datetime | None = None,
) -> list[FailedAutomationRun]:
    """Return the automation runs that failed and were not reported yet, oldest first.

    A run failed when its execution failed, when its execution has been running for longer than ``stuck_after``,
    or when its dispatch failed and will not be attempted again.
    This holds for every automation type, although only the types that record their execution can fail on it.

    :param stuck_after: How long a run may execute before it counts as stuck.
    :param now:         The moment to judge by, which defaults to the server's current time.
    """
    if now is None:
        now = server_now()
    now = now.astimezone(timezone.utc)
    execution_failed = AutomationRun.execution_state == "failed"
    stuck = and_(
        AutomationRun.execution_state == "running",
        AutomationRun.execution_started_at <= now - stuck_after,
    )
    runs = db.session.scalars(
        select(AutomationRun)
        .where(
            AutomationRun.alerted_at.is_(None),
            or_(execution_failed, stuck, _dispatch_failed_for_good(now)),
        )
        .options(
            selectinload(AutomationRun.automation)
            .joinedload(Automation.asset)
            .joinedload(GenericAsset.owner)
        )
        .order_by(
            AutomationRun.automation_id, AutomationRun.scheduled_at, AutomationRun.id
        )
    ).all()
    failed_runs = []
    for run in runs:
        if run.execution_state == "failed":
            reason = EXECUTION_FAILED
        elif (
            run.execution_state == "running"
            and run.execution_started_at <= now - stuck_after
        ):
            reason = STUCK
        else:
            reason = DISPATCH_FAILED
        failed_runs.append(FailedAutomationRun(run=run, reason=reason))
    return failed_runs


def group_failed_runs_by_automation(
    failed_runs: list[FailedAutomationRun],
) -> list[AutomationFailures]:
    """Collapse failed runs per automation, keeping the order in which the automations first appear."""
    failures: dict[int, AutomationFailures] = {}
    for failed_run in failed_runs:
        automation = failed_run.run.automation
        failures.setdefault(automation.id, AutomationFailures(automation=automation))
        failures[automation.id].failed_runs.append(failed_run)
    return list(failures.values())
