"""
Logic for running automations (see also the CLI command `flexmeasures jobs run-automations`).
"""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import socket
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cron_descriptor import get_description, Options
from croniter import croniter
from croniter.croniter import CroniterError
from flask import current_app
import isodate
from marshmallow import ValidationError
from rq.job import Job
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from flexmeasures import Forecaster
from flexmeasures.data import db
from flexmeasures.data.models.automations import (
    Automation,
    AutomationRun,
    AutomationRunAttempt,
    AutomationRunJob,
)
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.queries.generic_assets import (
    asset_and_ancestor_ids,
    asset_is_in_subtree,
)
from flexmeasures.utils.time_utils import server_now

AUTOMATION_RUN_CLAIM_LEASE = timedelta(minutes=10)
# Dispatch is only finished once `dispatch_completed_at` is set, so every other dispatch state is resumable.
# A run in one of these states is nevertheless off limits while another runner still holds a live claim on it.
AUTOMATION_RUN_RESUMABLE_DISPATCH_STATES = (
    "pending",
    "claimed",
    "partially_queued",
    "queued",
    "failed",
)


@dataclass(frozen=True)
class DueAutomation:
    """An automation together with the canonical run it should handle."""

    automation: Automation
    scheduled_at: datetime
    expected_cursor: datetime | None
    expected_cronstr: str
    expected_timezone: str


@dataclass(frozen=True)
class ClaimedAutomationRun:
    """An automation run and the attempt which currently owns its dispatch."""

    run: AutomationRun
    attempt: AutomationRunAttempt


class AutomationRunClaimError(Exception):
    """Raised when an automation occurrence cannot be claimed."""


def _runner_owner() -> str:
    """Return a short owner string for an automation-run claim lease."""
    return f"{socket.gethostname()}:{os.getpid()}"


def _now_utc() -> datetime:
    """Return the current database-facing time as timezone-aware UTC."""
    return server_now().astimezone(timezone.utc)


def _claim_expires_at(now: datetime, lease: timedelta) -> datetime:
    """Return the UTC timestamp at which a claim becomes stale."""
    return now + lease


def _claim_is_available(now: datetime):
    """Return the criterion for a run whose claim is free to take at ``now``.

    A claim is free when no runner holds it, or when the runner holding it let its lease expire, which is how a
    runner that died mid-dispatch releases its occurrence.
    """
    return or_(
        AutomationRun.claim_expires_at.is_(None),
        AutomationRun.claim_expires_at <= now,
    )


def _json_safe(value: Any) -> Any:
    """Convert values from an RQ job payload to JSON-compatible diagnostics."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, timedelta):
        return isodate.duration_isoformat(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _run_snapshot(automation: Automation, scheduled_at: datetime) -> dict[str, Any]:
    """Snapshot automation configuration for an immutable run plan."""
    return {
        "automation_id": automation.id,
        "automation_type": automation.type,
        "automation_name": automation.name,
        "asset_id": automation.asset_id,
        "scheduled_at": scheduled_at.astimezone(timezone.utc).isoformat(),
        "schedule_revision": automation.schedule_revision,
        "cronstr": automation.cronstr,
        "timezone": automation.timezone,
        "generator_id": automation.generator_id,
    }


def _new_attempt(run: AutomationRun, owner: str, now: datetime) -> AutomationRunAttempt:
    """Append a durable dispatch attempt to a claimed automation run."""
    attempt = AutomationRunAttempt(
        run=run,
        attempt_no=run.attempt_count,
        owner=owner,
        started_at=now,
        queued_job_count=run.queued_job_count,
    )
    db.session.add(attempt)
    return attempt


def _finish_attempt(
    attempt: AutomationRunAttempt | None,
    outcome: str,
    queued_job_count: int,
    error: BaseException | None = None,
) -> None:
    """Record the result of a dispatch attempt."""
    if attempt is None:
        return
    attempt.finished_at = _now_utc()
    attempt.outcome = outcome
    attempt.queued_job_count = queued_job_count
    if error is not None:
        attempt.error_type = error.__class__.__name__
        attempt.error_message = str(error)


def claim_due_automation_run(
    due_automation: DueAutomation,
    owner: str | None = None,
    lease: timedelta = AUTOMATION_RUN_CLAIM_LEASE,
) -> ClaimedAutomationRun | None:
    """Atomically claim a newly due occurrence and create its durable run."""
    owner = owner or _runner_owner()
    now = _now_utc()
    if due_automation.expected_cursor is None:
        cursor_matches = Automation.cursor.is_(None)
    else:
        cursor_matches = Automation.cursor == due_automation.expected_cursor
    result = db.session.execute(
        update(Automation)
        .where(
            Automation.id == due_automation.automation.id,
            Automation.active.is_(True),
            Automation.cronstr == due_automation.expected_cronstr,
            Automation.timezone == due_automation.expected_timezone,
            Automation.schedule_revision == due_automation.automation.schedule_revision,
            cursor_matches,
        )
        .values(cursor=due_automation.scheduled_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.session.rollback()
        return None

    automation = due_automation.automation
    run = AutomationRun(
        automation=automation,
        scheduled_at=due_automation.scheduled_at,
        schedule_revision=automation.schedule_revision,
        automation_type=automation.type,
        generator_id=automation.generator_id,
        dispatch_state="claimed",
        execution_state="pending",
        claim_owner=owner,
        claimed_at=now,
        claim_expires_at=_claim_expires_at(now, lease),
        attempt_count=1,
        parameters=dict(automation.parameters or {}),
        plan=_run_snapshot(automation, due_automation.scheduled_at),
    )
    db.session.add(run)
    db.session.flush()
    attempt = _new_attempt(run, owner, now)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None
    return ClaimedAutomationRun(run=run, attempt=attempt)


def claim_existing_automation_run(
    run: AutomationRun,
    owner: str | None = None,
    lease: timedelta = AUTOMATION_RUN_CLAIM_LEASE,
) -> ClaimedAutomationRun | None:
    """Claim a durable automation run whose dispatch is unfinished and unclaimed.

    A run is only up for grabs once no other runner holds a live claim on it, because the dispatch state turns to
    'partially_queued' while the owning runner is still queueing the rest of its jobs.
    A runner which fails releases its own claim, so its run is immediately retryable.
    """
    owner = owner or _runner_owner()
    now = _now_utc()
    result = db.session.execute(
        update(AutomationRun)
        .where(
            AutomationRun.id == run.id,
            AutomationRun.dispatch_state.in_(AUTOMATION_RUN_RESUMABLE_DISPATCH_STATES),
            AutomationRun.dispatch_completed_at.is_(None),
            _claim_is_available(now),
        )
        .values(
            dispatch_state="claimed",
            claim_owner=owner,
            claimed_at=now,
            claim_expires_at=_claim_expires_at(now, lease),
            attempt_count=AutomationRun.attempt_count + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.session.rollback()
        return None
    db.session.flush()
    claimed_run = db.session.get(AutomationRun, run.id)
    assert claimed_run is not None
    db.session.refresh(claimed_run)
    attempt = _new_attempt(claimed_run, owner, now)
    db.session.commit()
    return ClaimedAutomationRun(run=claimed_run, attempt=attempt)


def get_dispatchable_automation_runs(
    now: datetime | None = None,
    owner: str | None = None,
) -> list[ClaimedAutomationRun]:
    """Claim new due occurrences and resumable durable runs for dispatch."""
    if now is None:
        now = _now_utc()
    now = floor_to_minute(now)
    claimed_runs: list[ClaimedAutomationRun] = []
    for due_automation in get_due_automations(now):
        claimed = claim_due_automation_run(due_automation, owner=owner)
        if claimed is not None:
            claimed_runs.append(claimed)

    resumable_runs = db.session.scalars(
        select(AutomationRun)
        .join(Automation)
        .where(
            Automation.active.is_(True),
            AutomationRun.dispatch_state.in_(AUTOMATION_RUN_RESUMABLE_DISPATCH_STATES),
            AutomationRun.dispatch_completed_at.is_(None),
            _claim_is_available(now),
        )
        .order_by(AutomationRun.scheduled_at, AutomationRun.id)
    ).all()
    claimed_ids = {claimed.run.id for claimed in claimed_runs}
    for run in resumable_runs:
        if run.id in claimed_ids:
            continue
        claimed = claim_existing_automation_run(run, owner=owner)
        if claimed is not None:
            claimed_runs.append(claimed)
    return claimed_runs


def ensure_automation_run_job_intents(
    run_id: int, job_specs: list[dict[str, Any]]
) -> list[AutomationRunJob]:
    """Persist immutable logical job intents before any Redis enqueue."""
    run = db.session.get(AutomationRun, run_id)
    if run is None:
        raise ValueError(f"Automation run {run_id} does not exist.")
    existing_intents = {intent.logical_job_key: intent for intent in run.job_intents}
    if existing_intents:
        return [existing_intents[spec["logical_job_key"]] for spec in job_specs]

    run.plan = {
        **dict(run.plan or {}),
        "jobs": [_json_safe(spec) for spec in job_specs],
    }
    intents = []
    for spec in job_specs:
        intent = AutomationRunJob(
            run=run,
            logical_job_key=spec["logical_job_key"],
            rq_job_id=spec["rq_job_id"],
            queue=spec.get("queue", "forecasting"),
            kind=spec["kind"],
            status="pending",
            depends_on=list(spec.get("depends_on", [])),
            payload=_json_safe(spec.get("payload", {})),
        )
        db.session.add(intent)
        intents.append(intent)
    db.session.commit()
    return intents


def mark_automation_job_queued(
    run_id: int, logical_job_key: str, rq_job_id: str
) -> None:
    """Mark one logical job intent as queued in Redis."""
    now = _now_utc()
    intent = db.session.scalars(
        select(AutomationRunJob).filter_by(
            run_id=run_id, logical_job_key=logical_job_key
        )
    ).one()
    intent.status = "queued"
    intent.rq_job_id = rq_job_id
    intent.enqueued_at = intent.enqueued_at or now
    run = intent.run
    run.first_enqueued_at = run.first_enqueued_at or now
    queued_count = run.queued_job_count
    run.dispatch_state = (
        "queued" if queued_count == run.intended_job_count else "partially_queued"
    )
    db.session.commit()


def mark_automation_run_dispatch_queued(
    run_id: int, attempt: AutomationRunAttempt | None = None
) -> None:
    """Mark an automation run as fully queued and release its dispatch claim."""
    now = _now_utc()
    run = db.session.get(AutomationRun, run_id)
    if run is None:
        raise ValueError(f"Automation run {run_id} does not exist.")
    run.dispatch_state = "queued"
    run.dispatch_completed_at = now
    run.claim_owner = None
    run.claim_expires_at = None
    _finish_attempt(attempt, "queued", run.queued_job_count)
    db.session.commit()


def mark_automation_run_dispatch_failed(
    run_id: int,
    attempt: AutomationRunAttempt | None,
    error: BaseException,
) -> None:
    """Record a failed dispatch attempt and release the claim, so the run stays retryable.

    The failure may have come from the database itself, so roll back first to get a usable session,
    then re-read the run and the attempt through it.
    """
    db.session.rollback()
    run = db.session.get(AutomationRun, run_id)
    if run is None:
        raise ValueError(f"Automation run {run_id} does not exist.")
    if attempt is not None:
        attempt = db.session.get(AutomationRunAttempt, attempt.id)
    queued_count = run.queued_job_count
    run.dispatch_state = "partially_queued" if queued_count else "failed"
    run.last_error_type = error.__class__.__name__
    run.last_error_message = str(error)
    # Hand the occurrence back rather than making the next runner wait out this attempt's lease.
    run.claim_owner = None
    run.claim_expires_at = None
    _finish_attempt(attempt, run.dispatch_state, queued_count, error)
    db.session.commit()


def record_automation_job_started(
    run_id: int | None, logical_job_key: str | None
) -> None:
    """Record that a worker started an automation-created job."""
    if run_id is None or logical_job_key is None:
        return
    now = _now_utc()
    intent = db.session.scalars(
        select(AutomationRunJob).filter_by(
            run_id=run_id, logical_job_key=logical_job_key
        )
    ).one_or_none()
    if intent is None:
        return
    intent.status = "running"
    intent.started_at = intent.started_at or now
    intent.run.execution_state = "running"
    intent.run.execution_started_at = intent.run.execution_started_at or now
    db.session.commit()


def _refresh_run_execution_state(run: AutomationRun, now: datetime) -> None:
    """Derive a run's execution state from the state of all the jobs it created.

    A failed job keeps the whole run failed: a later job succeeding, as the wrap-up job does whatever became of the
    cycle jobs it reports on, must not put the run back to 'running' and bury the failure.
    """
    statuses = [job.status for job in run.job_intents]
    finished = all(status in ("succeeded", "failed", "canceled") for status in statuses)
    if "failed" in statuses:
        run.execution_state = "failed"
    elif finished and all(status == "succeeded" for status in statuses):
        run.execution_state = "succeeded"
    else:
        run.execution_state = "running"
    if finished or run.execution_state == "failed":
        run.execution_completed_at = run.execution_completed_at or now


def record_automation_job_succeeded(
    run_id: int | None, logical_job_key: str | None
) -> None:
    """Record that a worker finished an automation-created job successfully."""
    if run_id is None or logical_job_key is None:
        return
    now = _now_utc()
    intent = db.session.scalars(
        select(AutomationRunJob).filter_by(
            run_id=run_id, logical_job_key=logical_job_key
        )
    ).one_or_none()
    if intent is None:
        return
    intent.status = "succeeded"
    intent.finished_at = now
    _refresh_run_execution_state(intent.run, now)
    db.session.commit()


def record_automation_job_failed(
    run_id: int | None,
    logical_job_key: str | None,
    error: BaseException,
) -> None:
    """Record that a worker failed an automation-created job.

    The job may well have failed on the database itself, which leaves the session in an aborted transaction where
    every further statement is refused. Roll back first, so that the failure is still recorded. The job's own
    uncommitted work is lost either way, since it is failing.
    """
    if run_id is None or logical_job_key is None:
        return
    db.session.rollback()
    now = _now_utc()
    intent = db.session.scalars(
        select(AutomationRunJob).filter_by(
            run_id=run_id, logical_job_key=logical_job_key
        )
    ).one_or_none()
    if intent is None:
        return
    intent.status = "failed"
    intent.finished_at = now
    intent.last_error_type = error.__class__.__name__
    intent.last_error_message = str(error)
    run = intent.run
    _refresh_run_execution_state(run, now)
    run.last_error_type = error.__class__.__name__
    run.last_error_message = str(error)
    db.session.commit()


def reconcile_automation_job_intent(intent: AutomationRunJob) -> bool:
    """Return whether Redis already has the deterministic job for an intent."""
    connection = current_app.queues[intent.queue].connection
    if Job.exists(intent.rq_job_id, connection=connection):
        if intent.status == "pending":
            mark_automation_job_queued(
                intent.run_id, intent.logical_job_key, intent.rq_job_id
            )
        return True
    return False


def describe_cronstr(cronstr: str) -> str:
    """Describe a cron string in natural language, e.g. "At 06:00".

    Explicitly renders times in 24-hour format, as cron-descriptor otherwise
    picks a format based on the system locale.
    """
    options = Options()
    options.use_24hour_time_format = True
    try:
        return get_description(cronstr, options)
    except Exception:
        return cronstr


def floor_to_minute(dt: datetime) -> datetime:
    """Floor a timezone-aware datetime to a UTC minute."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Automation scheduling requires a timezone-aware datetime.")
    return dt.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _as_nominal_wall_time(dt: datetime) -> datetime:
    """Represent local wall-clock fields on a transition-free UTC timeline."""
    return datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, tzinfo=timezone.utc)


def _localize_nominal_time(
    nominal_time: datetime, timezone_info: ZoneInfo, fold: int
) -> datetime:
    """Attach a real timezone to nominal wall-clock fields using the given fold."""
    return datetime(
        nominal_time.year,
        nominal_time.month,
        nominal_time.day,
        nominal_time.hour,
        nominal_time.minute,
        tzinfo=timezone_info,
        fold=fold,
    )


def _is_valid_local_time(
    localized_time: datetime, nominal_time: datetime, timezone_info: ZoneInfo
) -> bool:
    """Return whether a localized time survives a UTC round trip unchanged."""
    round_tripped = localized_time.astimezone(timezone.utc).astimezone(timezone_info)
    return _as_nominal_wall_time(round_tripped) == nominal_time


def _valid_localizations(
    nominal_time: datetime, timezone_info: ZoneInfo
) -> list[datetime]:
    """Return the valid physical instants for a nominal wall-clock minute."""
    localizations = [
        _localize_nominal_time(nominal_time, timezone_info, fold=0),
        _localize_nominal_time(nominal_time, timezone_info, fold=1),
    ]
    valid_localizations = [
        localized_time
        for localized_time in localizations
        if _is_valid_local_time(localized_time, nominal_time, timezone_info)
    ]
    return list(
        {
            localized_time.astimezone(timezone.utc)
            for localized_time in valid_localizations
        }
    )


def _is_ambiguous_wall_time(nominal_time: datetime, timezone_info: ZoneInfo) -> bool:
    """Return whether a wall-clock minute denotes two physical instants."""
    return len(_valid_localizations(nominal_time, timezone_info)) == 2


def _canonical_run_time(nominal_time: datetime, timezone_info: ZoneInfo) -> datetime:
    """Map one wall-clock run to its canonical effective UTC instant.

    Ambiguous times use the earlier fold.
    Nonexistent times become effective at the first valid minute after the clock jump.
    """
    valid_localizations = _valid_localizations(nominal_time, timezone_info)
    if valid_localizations:
        return min(valid_localizations)

    first_valid_nominal_time = nominal_time
    for _ in range(60 * 48):
        first_valid_nominal_time += timedelta(minutes=1)
        valid_localizations = _valid_localizations(
            first_valid_nominal_time, timezone_info
        )
        if valid_localizations:
            return min(valid_localizations)
    raise ValueError(
        f"Could not find a valid local time after {nominal_time.isoformat()} in {timezone_info.key}."
    )


def _cron_evaluation_time(now: datetime, timezone_info: ZoneInfo) -> datetime:
    """Return the nominal wall time through which cron runs have happened.

    During the second fold of a repeated interval, the entire first fold has already happened.
    Evaluate through the end of that repeated wall interval, so missed runs are coalesced instead of replayed minute by minute.
    """
    localized_now = now.astimezone(timezone_info)
    nominal_now = _as_nominal_wall_time(localized_now)
    if localized_now.fold != 1 or not _is_ambiguous_wall_time(
        nominal_now, timezone_info
    ):
        return nominal_now

    nominal_after_overlap = nominal_now
    for _ in range(60 * 48):
        nominal_after_overlap += timedelta(minutes=1)
        if not _is_ambiguous_wall_time(nominal_after_overlap, timezone_info):
            return nominal_after_overlap - timedelta(minutes=1)
    raise ValueError(
        f"Could not find the end of the repeated local-time interval in {timezone_info.key}."
    )


def get_latest_scheduled_run(automation: Automation, now: datetime) -> datetime:
    """Return the latest canonical run for an automation through ``now``."""
    now = floor_to_minute(now)
    timezone_info = ZoneInfo(automation.timezone)
    evaluation_time = _cron_evaluation_time(now, timezone_info)
    if croniter.match(automation.cronstr, evaluation_time):
        nominal_run = evaluation_time
    else:
        nominal_run = croniter(automation.cronstr, evaluation_time).get_prev(datetime)
    scheduled_at = _canonical_run_time(nominal_run, timezone_info)
    if scheduled_at > now:
        raise ValueError(
            f"Cron run {nominal_run.isoformat()} in {automation.timezone} resolves after {now.isoformat()}."
        )
    return scheduled_at


def get_due_automations(now: datetime | None = None) -> list[DueAutomation]:
    """Return the newest unhandled run for each active automation."""
    if now is None:
        now = server_now()
    now = floor_to_minute(now)
    active_automations = (
        db.session.scalars(select(Automation).filter_by(active=True)).unique().all()
    )
    due_automations = []
    for automation in active_automations:
        try:
            scheduled_at = get_latest_scheduled_run(automation, now)
        except (CroniterError, ValueError, ZoneInfoNotFoundError) as exc:
            current_app.logger.error(
                "Skipping automation %s (%r), because its next run could not be calculated: %s",
                automation.id,
                automation.name,
                exc,
            )
            continue
        expected_cursor = automation.cursor
        cursor = expected_cursor
        if cursor is None:
            cursor = floor_to_minute(automation.created_at) - timedelta(minutes=1)
        if scheduled_at > cursor:
            due_automations.append(
                DueAutomation(
                    automation=automation,
                    scheduled_at=scheduled_at,
                    expected_cursor=expected_cursor,
                    expected_cronstr=automation.cronstr,
                    expected_timezone=automation.timezone,
                )
            )
    return due_automations


class AutomationSensorsUnknown(Exception):
    """Raised when the sensors an automation involves cannot be worked out.

    Callers that decide whether something is allowed must let this propagate rather than treat it as "no sensors",
    because an automation with no known sensors would otherwise pass every check on the sensors it involves.
    """


def resolve_automation_sensors(automation: Automation) -> dict[str, list[Sensor]]:
    """Work out which sensors an automation reads from and writes to on each run.

    The sensors are derived from the data generator, configured with the automation's own parameters.
    Raises `AutomationSensorsUnknown` if that cannot be done, e.g. because the automation has no data generator,
    because its generator is not registered in this FlexMeasures instance,
    or because its parameters no longer load (say, after a sensor was deleted).
    Use this wherever the answer decides whether something is permitted; use `get_automation_sensors` for display.
    """
    if automation.generator is None:
        raise AutomationSensorsUnknown(
            f"Automation {automation.id} has no data generator, so the sensors it involves are unknown."
        )
    try:
        # Work on a copy, as the data generator is cached on the data source,
        # which may be shared by several automations.
        data_generator = copy(automation.generator.data_generator)
        data_generator._parameters = data_generator._parameters_schema.load(
            dict(automation.parameters or {})
        )
        return {
            "input_sensors": data_generator.input_sensors,
            "output_sensors": data_generator.output_sensors,
        }
    except (NotImplementedError, ValidationError) as e:
        raise AutomationSensorsUnknown(
            f"Could not determine the sensors of automation {automation.id}: {e}"
        ) from e


def get_automation_sensors(automation: Automation) -> dict[str, list[Sensor]]:
    """Look up which sensors an automation reads from and writes to on each run, for display purposes.

    Automations whose sensors cannot be worked out report no sensors, so that one broken automation
    does not keep a page or an API response from rendering.
    Do not use this to decide whether something is permitted, as "no sensors" then reads as "nothing to check":
    call `resolve_automation_sensors` instead and let its error propagate.
    """
    try:
        return resolve_automation_sensors(automation)
    except AutomationSensorsUnknown as e:
        current_app.logger.warning(str(e))
        return {"input_sensors": [], "output_sensors": []}


def get_automations_feeding_sensor(sensor: Sensor) -> list[Automation]:
    """Find the automations that write data to the given sensor.

    Only automations on the sensor's own asset or on one of its ancestors are
    considered, as an automation may only write to its asset's subtree
    (see `validate_forecast_output_scope`). Working out the output sensors requires
    setting up each candidate's data generator, so this keeps the work proportional
    to the number of automations that could feed this sensor.

    Note that this does not filter by permission: callers showing these to a user
    should check read access on each automation (e.g. with `user_can_read`).
    """
    candidate_automations = db.session.scalars(
        select(Automation).filter(
            Automation.asset_id.in_(asset_and_ancestor_ids(sensor.generic_asset_id))
        )
    ).unique()
    return [
        automation
        for automation in candidate_automations
        if sensor.id in [output.id for output in automation.output_sensors]
    ]


def get_automations_involving_sensor(sensor: Sensor) -> list[Automation]:
    """Find the automations that read from or write to the given sensor.

    Unlike `get_automations_feeding_sensor`, this considers every automation, because a regressor
    may live anywhere in the tree, not just on the sensor's asset or one of its ancestors.
    That makes this proportional to the number of automations, so keep it out of hot paths;
    it is meant for rare, interactive checks, such as warning before a sensor is deleted.
    """
    involved = []
    for automation in db.session.scalars(select(Automation)).unique():
        automation_sensors = get_automation_sensors(automation)
        if sensor.id in {
            involved_sensor.id
            for key in ("input_sensors", "output_sensors")
            for involved_sensor in automation_sensors[key]
        }:
            involved.append(automation)
    return involved


def get_automation_job_stats(automation: Automation) -> dict[str, int]:
    """Count the jobs created by this automation, per job status.

    Note that jobs in Redis have a limited TTL, so this only counts fairly recent jobs.
    """
    # Jobs are cached under the forecast target sensor(s), which may belong
    # to a different asset than the automation's own asset.
    sensor_ids = {sensor.id for sensor in automation.asset.sensors}
    for key in ("sensor", "sensor-to-save"):
        value = (automation.parameters or {}).get(key)
        if value is not None:
            try:
                sensor_ids.add(int(value))
            except (TypeError, ValueError):
                pass

    counts: dict[str, int] = {}
    seen_job_ids: set[str] = set()
    for sensor_id in sensor_ids:
        for job in current_app.job_cache.get(sensor_id, "forecasting", "sensor"):
            if job.id in seen_job_ids:
                continue
            seen_job_ids.add(job.id)
            if job.meta.get("trigger", {}).get("automation_id") == automation.id:
                status = str(job.get_status().value)
                counts[status] = counts.get(status, 0) + 1
    return counts


def serialize_automation_run(run: AutomationRun) -> dict[str, Any]:
    """Return operator-facing durable status for one automation run."""
    latest_attempt = run.attempts[-1] if run.attempts else None
    return {
        "id": run.id,
        "scheduled_at": run.scheduled_at.isoformat(),
        "schedule_revision": run.schedule_revision,
        "dispatch_state": run.dispatch_state,
        "execution_state": run.execution_state,
        "attempt_count": run.attempt_count,
        "intended_job_count": run.intended_job_count,
        "queued_job_count": run.queued_job_count,
        "first_enqueued_at": (
            run.first_enqueued_at.isoformat() if run.first_enqueued_at else None
        ),
        "dispatch_completed_at": (
            run.dispatch_completed_at.isoformat() if run.dispatch_completed_at else None
        ),
        "execution_completed_at": (
            run.execution_completed_at.isoformat()
            if run.execution_completed_at
            else None
        ),
        "claim_owner": run.claim_owner,
        "claim_expires_at": (
            run.claim_expires_at.isoformat() if run.claim_expires_at else None
        ),
        "last_error": (
            {
                "type": run.last_error_type,
                "message": run.last_error_message,
            }
            if run.last_error_type or run.last_error_message
            else None
        ),
        "latest_attempt": (
            {
                "attempt_no": latest_attempt.attempt_no,
                "owner": latest_attempt.owner,
                "started_at": latest_attempt.started_at.isoformat(),
                "finished_at": (
                    latest_attempt.finished_at.isoformat()
                    if latest_attempt.finished_at
                    else None
                ),
                "outcome": latest_attempt.outcome,
                "queued_job_count": latest_attempt.queued_job_count,
                "error": (
                    {
                        "type": latest_attempt.error_type,
                        "message": latest_attempt.error_message,
                    }
                    if latest_attempt.error_type or latest_attempt.error_message
                    else None
                ),
            }
            if latest_attempt is not None
            else None
        ),
        "jobs": [
            {
                "logical_job_key": intent.logical_job_key,
                "rq_job_id": intent.rq_job_id,
                "queue": intent.queue,
                "kind": intent.kind,
                "status": intent.status,
                "depends_on": list(intent.depends_on or []),
                "enqueued_at": (
                    intent.enqueued_at.isoformat() if intent.enqueued_at else None
                ),
                "started_at": (
                    intent.started_at.isoformat() if intent.started_at else None
                ),
                "finished_at": (
                    intent.finished_at.isoformat() if intent.finished_at else None
                ),
                "last_error": (
                    {
                        "type": intent.last_error_type,
                        "message": intent.last_error_message,
                    }
                    if intent.last_error_type or intent.last_error_message
                    else None
                ),
            }
            for intent in run.job_intents
        ],
    }


def get_automation_run_stats(automation: Automation) -> dict[str, Any]:
    """Summarize durable automation runs for API and UI status displays."""
    runs = list(automation.runs)
    dispatch_counts: dict[str, int] = {}
    execution_counts: dict[str, int] = {}
    for run in runs:
        dispatch_counts[run.dispatch_state] = (
            dispatch_counts.get(run.dispatch_state, 0) + 1
        )
        execution_counts[run.execution_state] = (
            execution_counts.get(run.execution_state, 0) + 1
        )
    latest_run = runs[0] if runs else None
    return {
        "total": len(runs),
        "dispatch": dispatch_counts,
        "execution": execution_counts,
        "latest_run": (
            serialize_automation_run(latest_run) if latest_run is not None else None
        ),
        "recent_runs": [serialize_automation_run(run) for run in runs[:10]],
    }


def get_forecast_output_sensor(parameters: dict[str, Any]) -> Sensor:
    """Resolve the sensor on which a forecast automation registers beliefs."""
    sensor_reference = parameters.get("sensor-to-save")
    if sensor_reference is None:
        sensor_reference = parameters.get("sensor_to_save")
    if sensor_reference is None:
        sensor_reference = parameters.get("sensor")

    if isinstance(sensor_reference, Sensor):
        return sensor_reference
    try:
        sensor_id = int(sensor_reference)
    except (TypeError, ValueError) as exc:
        raise ValueError("Forecast automation has no valid output sensor.") from exc

    sensor = db.session.get(Sensor, sensor_id)
    if sensor is None:
        raise ValueError(
            f"Forecast automation output sensor {sensor_id} does not exist."
        )
    return sensor


def validate_forecast_output_scope(asset_id: int, output_sensor: Sensor) -> None:
    """Require forecast output on the automation asset or a descendant."""
    if not asset_is_in_subtree(asset_id, output_sensor.generic_asset_id):
        raise ValueError(
            f"Forecast automation output sensor {output_sensor.id} must belong to asset "
            f"{asset_id} or one of its descendants."
        )


def dispatch_automation_run(
    claimed_run: ClaimedAutomationRun,
) -> dict[str, Any]:
    """Dispatch an already claimed automation run and record its attempt outcome."""
    run = claimed_run.run
    try:
        returns = run_automation(run.automation, automation_run=run)
    except Exception as exc:
        mark_automation_run_dispatch_failed(run.id, claimed_run.attempt, exc)
        raise
    mark_automation_run_dispatch_queued(run.id, claimed_run.attempt)
    return {
        "run_id": run.id,
        "job_id": returns.get("job_id") if returns else None,
        "n_jobs": returns.get("n_jobs") if returns else 0,
        "dispatch_state": "queued",
    }


def run_automation(
    automation: Automation, automation_run: AutomationRun | None = None
) -> dict[str, Any] | None:
    """Queue the jobs for one run of an automation.

    :returns: the data generator's return value, e.g. {"job_id": <uuid>, "n_jobs": <int>}
              for forecasting jobs.
    """
    if automation.type != "forecasts":
        raise NotImplementedError(
            f"Automations of type '{automation.type}' cannot be run yet."
        )
    if automation.generator is None:
        raise ValueError(
            f"Automation {automation.id} has no data generator to run (generator_id is not set)."
        )
    # Work on a copy, as the data generator is cached on the data source,
    # which may be shared by several automations (as in `resolve_automation_sensors`).
    forecaster = copy(automation.generator.data_generator)
    if not isinstance(forecaster, Forecaster):
        raise ValueError(
            f"Data source {automation.generator_id} of automation {automation.id} does not store a Forecaster."
        )
    parameters = (
        dict(automation_run.parameters)
        if automation_run is not None
        else dict(automation.parameters)
    )
    output_sensor = get_forecast_output_sensor(parameters)
    validate_forecast_output_scope(automation.asset_id, output_sensor)
    # Wipe any parameter state the copy inherited from a previous run.
    forecaster._parameters = None
    forecaster.set_job_trigger(
        "automation",
        automation_id=automation.id,
        automation_run_id=automation_run.id if automation_run is not None else None,
    )
    return forecaster.compute(as_job=True, parameters=parameters)
