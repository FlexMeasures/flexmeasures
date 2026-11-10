"""Hooks that a host can implement to act on the failure of a critical automation.

FlexMeasures decides nothing about what a critical failure means for an organisation:
one pages the engineer on duty, another opens a ticket, a third writes to a status page.
So it only reports the failure, and leaves the business logic to the host.

A hook is a callable taking one `CriticalAutomationFailure`. Register it either

- from a plugin, by exposing callables in the module's ``__automation_failure_hooks__``, or
- from server settings, by naming dotted import paths in
  ``FLEXMEASURES_CRITICAL_AUTOMATION_FAILURE_HOOKS``,

which is for a host that wants to point at a function without writing a plugin.

Hooks run inside the dispatcher or the worker that recorded the failure, straight after it was
recorded and committed. They are expected to be quick and to do their own error handling;
a hook that raises is logged and skipped, and never fails the run it was told about, which has
failed already. Anything slow belongs on a queue of the host's own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from typing import Callable

from flask import current_app

from flexmeasures.data import db
from flexmeasures.data.models.automations import Automation, AutomationRun
from flexmeasures.utils.time_utils import server_now


@dataclass(frozen=True)
class CriticalAutomationFailure:
    """What a hook is told about a failed run of an automation flagged as critical.

    Plain values rather than ORM objects, so a hook can hand this to a pager, a webhook or a
    queue without holding on to a database session. Use `automation_id` and `run_id` to look
    the records up where more is needed.
    """

    automation_id: int
    automation_name: str
    automation_type: str
    asset_id: int
    asset_name: str
    run_id: int
    scheduled_at: datetime
    # "dispatch" when FlexMeasures could not queue the run's jobs and has given up retrying,
    # "execution" when a job of the run failed on a worker.
    stage: str
    error_type: str | None
    error_message: str | None
    dispatch_state: str
    execution_state: str
    attempt_count: int
    intended_job_count: int
    queued_job_count: int

    @property
    def summary(self) -> str:
        """One line naming the automation, the run and what went wrong."""
        return (
            f"Critical automation '{self.automation_name}' (ID {self.automation_id},"
            f" {self.automation_type} on asset {self.asset_name}) failed during {self.stage}"
            f" on run {self.run_id}, scheduled for {self.scheduled_at.isoformat()}:"
            f" {self.error_type or 'unknown error'}: {self.error_message or ''}".rstrip()
        )


def initialize_automation_failure_hooks(app) -> None:
    """Install an empty hook registry on this application.

    Called before plugins are registered, as they add to it.
    """
    app.automation_failure_hooks = []


def register_automation_failure_hook(app, hook: Callable) -> None:
    """Register a hook to call when a run of a critical automation fails."""
    if not callable(hook):
        raise TypeError(
            "A critical-automation-failure hook must be callable,"
            f" and {hook!r} is not."
        )
    if hook in app.automation_failure_hooks:
        raise ValueError(f"Hook {_hook_name(hook)} is already registered.")
    app.automation_failure_hooks.append(hook)


def _hook_name(hook: Callable) -> str:
    """Name a hook well enough to find it in a log line."""
    module = getattr(hook, "__module__", "?")
    name = getattr(hook, "__qualname__", repr(hook))
    return f"{module}.{name}"


def _configured_hooks() -> list[Callable]:
    """Resolve the hooks named by dotted path in the server settings.

    Resolved on each failure rather than at startup, so a host that mistypes a path learns about
    it in the logs of the failure it missed, instead of having the server refuse to start.
    """
    hooks = []
    for path in current_app.config.get(
        "FLEXMEASURES_CRITICAL_AUTOMATION_FAILURE_HOOKS", []
    ):
        try:
            module_path, _, attribute = str(path).rpartition(".")
            if not module_path:
                raise ValueError("not a dotted path to a callable")
            hook = getattr(import_module(module_path), attribute)
            if not callable(hook):
                raise TypeError("is not callable")
        except Exception as exc:
            current_app.logger.error(
                f"[AUTOMATIONS] Cannot use critical-automation-failure hook '{path}': {exc}."
            )
            continue
        hooks.append(hook)
    return hooks


def get_automation_failure_hooks() -> list[Callable]:
    """Return every registered hook: the ones plugins added, then the ones settings name."""
    return (
        list(getattr(current_app, "automation_failure_hooks", [])) + _configured_hooks()
    )


def describe_critical_failure(
    run: AutomationRun, stage: str
) -> CriticalAutomationFailure:
    """Describe a failed run the way a hook is told about it."""
    automation: Automation = run.automation
    asset = automation.asset
    return CriticalAutomationFailure(
        automation_id=automation.id,
        automation_name=automation.name,
        automation_type=automation.type,
        asset_id=asset.id,
        asset_name=asset.name,
        run_id=run.id,
        scheduled_at=run.scheduled_at,
        stage=stage,
        error_type=run.last_error_type,
        error_message=run.last_error_message,
        dispatch_state=run.dispatch_state,
        execution_state=run.execution_state,
        attempt_count=run.attempt_count,
        intended_job_count=run.intended_job_count,
        queued_job_count=run.queued_job_count,
    )


def notify_critical_automation_failure(run: AutomationRun, stage: str) -> bool:
    """Hand a failed run to the critical-failure hooks, once.

    Does nothing unless the automation is flagged critical. A run notifies once, however many of
    its jobs fail and however often its dispatch is retried, which is recorded on the run itself
    so that a second dispatcher or worker does not page again.

    Never raises: this is called while recording a failure, and a hook that misbehaves must not
    cost us the record of what failed.

    :returns: whether the hooks were called for this run.
    """
    try:
        automation = run.automation
        if automation is None or not automation.critical:
            return False
        if run.critical_failure_notified_at is not None:
            return False
        failure = describe_critical_failure(run, stage)
        # Claim the notification before calling anything, so a hook that is slow or that crashes
        # the process does not have the next attempt page all over again.
        run.critical_failure_notified_at = server_now()
        db.session.commit()
    except Exception as exc:
        current_app.logger.error(
            f"[AUTOMATIONS] Could not prepare the critical-failure hooks for run {run.id}: {exc}."
        )
        db.session.rollback()
        return False

    current_app.logger.error(f"[AUTOMATIONS] {failure.summary}")
    for hook in get_automation_failure_hooks():
        try:
            hook(failure)
        except Exception as exc:
            current_app.logger.error(
                f"[AUTOMATIONS] Critical-automation-failure hook {_hook_name(hook)}"
                f" raised on run {run.id}: {exc!r}."
            )
    return True
