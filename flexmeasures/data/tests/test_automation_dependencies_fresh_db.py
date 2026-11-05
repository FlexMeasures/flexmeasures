"""Automations that wait for the runs of other automations: validation, and how the runner holds, releases and skips their runs."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from marshmallow import ValidationError
from redis.exceptions import RedisError
from rq.job import Job, JobStatus
from sqlalchemy import select

from flexmeasures.data.automations import register_automation_handler
from flexmeasures.data.models.automations import Automation, AutomationRun
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services import automations as automation_services
from flexmeasures.data.services.automations import (
    create_automation,
    dispatch_automation_run,
    get_dispatchable_automation_runs,
    run_automation,
    get_ascendant_automations,
    plan_automation_chain,
    run_automation_chain,
    run_automation_with_ascendants,
    update_automation,
)
from flexmeasures.data.tests.plugins.mock_ingestion import (
    MockIngestionGenerator,
    __automation_types__,
)
from flexmeasures.utils.job_utils import work_on_rq

# Every automation here recurs hourly and was created well before the run at 01:00, which a runner ticking at 01:00 dispatches.
CREATED_AT = datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc)
SCHEDULED_AT = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
TICK = datetime(2026, 8, 5, 1, 0, 30, tzinfo=timezone.utc)


@pytest.fixture
def ingestion_plugin(app, monkeypatch):
    monkeypatch.setattr(app, "automation_handlers", dict(app.automation_handlers))
    monkeypatch.setattr(
        app,
        "data_generators",
        {key: dict(value) for key, value in app.data_generators.items()},
    )
    register_automation_handler(app, __automation_types__[0])
    app.redis_connection.flushdb()
    yield
    app.redis_connection.flushdb()


@pytest.fixture
def failing_value(monkeypatch):
    """Have an ingestion job fail when its automation's parameters ask for a negative value."""
    compute = MockIngestionGenerator._compute

    def _compute(self, value):
        if value < 0:
            raise ValueError("The external system was unreachable.")
        return compute(self, value)

    monkeypatch.setattr(MockIngestionGenerator, "_compute", _compute)


@pytest.fixture
def make_automation(fresh_db, ingestion_plugin):
    """Create hourly ingestion automations on one asset, each due at 01:00, optionally waiting for others."""
    asset = GenericAsset(
        name="Dependency site",
        generic_asset_type=GenericAssetType(name="Dependency asset type"),
    )
    sensor = Sensor(name="measurement", generic_asset=asset, unit="kWh")
    fresh_db.session.add(sensor)
    fresh_db.session.commit()

    def _make_automation(
        name: str,
        depends_on: list[Automation] = (),
        allow_failure: bool = False,
        value: float = 1.0,
        cronstr: str = "0 * * * *",
        tz: str = "UTC",
    ) -> Automation:
        automation, _ = create_automation(
            asset=asset,
            name=name,
            cronstr=cronstr,
            timezone=tz,
            automation_type="mock-ingestion",
            config={"sensor": sensor.id},
            parameters={"value": value},
            dependencies=[
                {"upstream": upstream, "allow_failure": allow_failure}
                for upstream in depends_on
            ],
        )
        automation.created_at = CREATED_AT
        automation.cursor = CREATED_AT
        fresh_db.session.commit()
        return automation

    return _make_automation


def _tick(now: datetime = TICK) -> dict[int, dict]:
    """Claim and dispatch what a runner would at this moment, dependents first, which is the order that makes them wait."""
    claimed_runs = get_dispatchable_automation_runs(now)
    claimed_runs.sort(key=lambda claimed: -claimed.run.automation_id)
    return {
        claimed.run.automation_id: dispatch_automation_run(claimed)
        for claimed in claimed_runs
    }


def _run_of(db, automation: Automation) -> AutomationRun:
    db.session.expire_all()
    return db.session.scalars(
        select(AutomationRun).where(AutomationRun.automation_id == automation.id)
    ).one()


def _work(app, run: AutomationRun) -> None:
    """Have a worker run the jobs a run recorded."""
    for intent in run.job_intents:
        work_on_rq(
            app.queues[intent.queue],
            job=Job.fetch(intent.rq_job_id, connection=app.redis_connection),
        )


def test_a_dependent_run_waits_and_then_runs_once_its_upstream_run_succeeded(
    fresh_db, app, make_automation
):
    """The dependent run queues nothing while the upstream job runs, and its job is queued as soon as that job succeeded."""
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])

    returns = _tick()

    assert returns[flows.id]["dispatch_state"] == "waiting"
    flows_run = _run_of(fresh_db, flows)
    assert flows_run.dispatch_state == "waiting"
    assert flows_run.job_intents == []
    assert flows_run.claim_owner is None
    snapper_run = _run_of(fresh_db, snapper)
    assert flows_run.plan["upstream-runs"] == [
        {
            "automation": snapper.id,
            "allow-failure": False,
            "due-at": SCHEDULED_AT.isoformat(),
            "run": snapper_run.id,
            "state": "pending",
        }
    ]

    _work(app, snapper_run)

    flows_run = _run_of(fresh_db, flows)
    assert flows_run.dispatch_state == "queued"
    assert [intent.status for intent in flows_run.job_intents] == ["queued"]
    assert [attempt.outcome for attempt in flows_run.attempts] == ["waiting", "queued"]
    _work(app, flows_run)
    assert _run_of(fresh_db, flows).execution_state == "succeeded"


def test_a_dependent_run_is_skipped_when_its_upstream_run_failed(
    fresh_db, app, make_automation, failing_value
):
    """Without allowing for failure, a failed upstream run ends the dependent run without queueing anything, and says why."""
    snapper = make_automation("Snap meter readings", value=-1)
    flows = make_automation("Compute flows", depends_on=[snapper])
    _tick()

    _work(app, _run_of(fresh_db, snapper))

    flows_run = _run_of(fresh_db, flows)
    assert flows_run.execution_state == "skipped"
    assert flows_run.execution_completed_at is not None
    assert flows_run.dispatch_completed_at is not None
    assert flows_run.job_intents == []
    assert flows_run.last_error_type == "UpstreamRunFailed"
    assert f"automation(s) {snapper.id}" in flows_run.last_error_message
    queued_for = {
        Job.fetch(job_id, connection=app.redis_connection).meta["trigger"][
            "automation_id"
        ]
        for job_id in app.queues["ingestion"].job_ids
    }
    assert flows.id not in queued_for


def test_a_dependent_run_that_allows_for_failure_runs_anyway(
    fresh_db, app, make_automation, failing_value
):
    """Allowing for failure, the dependent run still waits for the upstream run, and then goes ahead although it failed."""
    snapper = make_automation("Snap meter readings", value=-1)
    flows = make_automation("Compute flows", depends_on=[snapper], allow_failure=True)
    assert _tick()[flows.id]["dispatch_state"] == "waiting"

    _work(app, _run_of(fresh_db, snapper))

    flows_run = _run_of(fresh_db, flows)
    assert flows_run.dispatch_state == "queued"
    assert len(flows_run.job_intents) == 1


def test_a_skip_cascades_down_a_chain(fresh_db, app, make_automation, failing_value):
    """A run skipped for a failed upstream run did not deliver its own results, so what waits for it is skipped, too."""
    snapper = make_automation("Snap meter readings", value=-1)
    flows = make_automation("Compute flows", depends_on=[snapper])
    totals = make_automation("Sum flows", depends_on=[flows])
    returns = _tick()
    assert returns[totals.id]["dispatch_state"] == "waiting"

    _work(app, _run_of(fresh_db, snapper))

    assert _run_of(fresh_db, flows).execution_state == "skipped"
    assert _run_of(fresh_db, totals).execution_state == "skipped"


def _kill_job_as_rq_finds_it(app, job: Job) -> None:
    """Leave a job as RQ does when the work-horse running it was killed, so that it never got to report."""
    job.set_status(JobStatus.FAILED)


def _lose_job(app, job: Job) -> None:
    """Have a job leave Redis without a trace, as when its hash expired."""
    job.delete()


def _abandon_job(app, job: Job) -> None:
    """Leave a job as a worker does that disappeared altogether: started, with a heartbeat that lapsed long ago."""
    job.set_status(JobStatus.STARTED)
    app.queues["ingestion"].remove(job.id)
    app.redis_connection.zadd(
        app.queues["ingestion"].started_job_registry.key,
        {f"{job.id}:execution": 1},
    )


@pytest.mark.parametrize(
    "end_job, error_type",
    [(_kill_job_as_rq_finds_it, None), (_lose_job, "JobLost"), (_abandon_job, None)],
)
@pytest.mark.parametrize("on_demand", [False, True])
def test_a_killed_job_ends_its_run_and_what_waits_for_it(
    fresh_db, app, make_automation, end_job, error_type, on_demand
):
    """A job that gets killed cannot say so, so the runner finds out, and what waits for its run is not left waiting forever."""
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])
    totals = make_automation("Sum flows", depends_on=[flows])
    if on_demand:
        returns, dependent_runs = run_automation_chain(snapper, now=TICK)
        snapper_run = fresh_db.session.get(AutomationRun, returns["run_id"])
    else:
        _tick()
        snapper_run = _run_of(fresh_db, snapper)
        dependent_runs = [_run_of(fresh_db, flows), _run_of(fresh_db, totals)]
    run_id, dependent_run_ids = snapper_run.id, [run.id for run in dependent_runs]
    intent = snapper_run.job_intents[0]
    # The worker got this far before it died.
    automation_services.record_automation_job_started(run_id, intent.logical_job_key)
    end_job(app, Job.fetch(intent.rq_job_id, connection=app.redis_connection))

    automation_services.reconcile_unfinished_automation_jobs()

    fresh_db.session.expire_all()
    snapper_run = fresh_db.session.get(AutomationRun, run_id)
    assert snapper_run.execution_state == "failed"
    assert snapper_run.execution_completed_at is not None
    if error_type is not None:
        assert snapper_run.last_error_type == error_type
    for dependent_run_id in dependent_run_ids:
        assert (
            fresh_db.session.get(AutomationRun, dependent_run_id).execution_state
            == "skipped"
        )


@pytest.mark.parametrize(
    "status", [JobStatus.QUEUED, JobStatus.STARTED, JobStatus.DEFERRED]
)
def test_a_job_that_has_yet_to_end_is_left_alone(
    fresh_db, app, make_automation, status
):
    """However long a job takes, the runner does not call it over, and what waits for its run goes on waiting."""
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])
    _tick()
    snapper_run = _run_of(fresh_db, snapper)
    job = Job.fetch(
        snapper_run.job_intents[0].rq_job_id, connection=app.redis_connection
    )
    job.set_status(status)

    _tick(datetime(2026, 8, 5, 6, 0, 30, tzinfo=timezone.utc))

    fresh_db.session.expire_all()
    assert _run_at(fresh_db, snapper, SCHEDULED_AT).execution_completed_at is None
    assert _run_at(fresh_db, flows, SCHEDULED_AT).dispatch_state == "waiting"


def test_the_runner_looks_up_unfinished_jobs_on_each_tick(
    fresh_db, app, make_automation
):
    """Nothing else would notice that a job was killed, so a tick has to."""
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])
    _tick()
    Job.fetch(
        _run_of(fresh_db, snapper).job_intents[0].rq_job_id,
        connection=app.redis_connection,
    ).set_status(JobStatus.FAILED)

    _tick(datetime(2026, 8, 5, 1, 1, 30, tzinfo=timezone.utc))

    assert _run_of(fresh_db, snapper).execution_state == "failed"
    assert _run_of(fresh_db, flows).execution_state == "skipped"


def test_a_job_that_finished_without_reporting_counts_as_succeeded(
    fresh_db, app, make_automation
):
    """A worker can go down between a job finishing and its report, which is no reason to skip what waits for it."""
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])
    _tick()
    snapper_run = _run_of(fresh_db, snapper)
    Job.fetch(
        snapper_run.job_intents[0].rq_job_id, connection=app.redis_connection
    ).set_status(JobStatus.FINISHED)

    _tick(datetime(2026, 8, 5, 1, 1, 30, tzinfo=timezone.utc))

    assert _run_of(fresh_db, snapper).execution_state == "succeeded"
    assert _run_of(fresh_db, flows).dispatch_state == "queued"


def test_a_runner_goes_on_without_redis_when_looking_up_unfinished_jobs(
    fresh_db, app, make_automation, monkeypatch
):
    """Not being able to reach Redis says nothing about a job, so its run stays as it is, for the next tick to look at."""
    snapper = make_automation("Snap meter readings")
    _tick()

    def unreachable(*args, **kwargs):
        raise RedisError("Connection refused")

    monkeypatch.setattr(Job, "fetch_many", unreachable)
    automation_services.reconcile_unfinished_automation_jobs()

    assert _run_of(fresh_db, snapper).execution_completed_at is None


def test_a_waiting_run_whose_release_was_missed_is_picked_up_by_the_next_tick(
    fresh_db, app, make_automation, monkeypatch
):
    """Should the upstream run end without releasing its dependents, the runner dispatches them on its next tick."""
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])
    _tick()
    with monkeypatch.context() as patch:
        patch.setattr(
            automation_services,
            "release_automation_runs_waiting_for",
            lambda run: None,
        )
        _work(app, _run_of(fresh_db, snapper))
    assert _run_of(fresh_db, flows).dispatch_state == "waiting"

    returns = _tick(datetime(2026, 8, 5, 1, 1, 30, tzinfo=timezone.utc))

    assert returns[flows.id]["dispatch_state"] == "queued"
    assert _run_of(fresh_db, flows).dispatch_state == "queued"


def test_a_waiting_run_stays_waiting_on_a_tick_while_its_upstream_run_is_pending(
    fresh_db, app, make_automation
):
    """The runner leaves a waiting run alone for as long as the run it waits for has not ended."""
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])
    _tick()

    assert _tick(datetime(2026, 8, 5, 1, 1, 30, tzinfo=timezone.utc)) == {}
    assert _run_of(fresh_db, flows).dispatch_state == "waiting"


def test_a_run_whose_upstream_automation_passed_over_that_time_is_skipped(
    fresh_db, make_automation
):
    """An upstream automation that moved past the scheduled time without a run there will never produce the input, so the run is skipped."""
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])
    # As if the upstream automation's missed run at 01:00 were left out by a bounded catch-up.
    snapper.cursor = SCHEDULED_AT
    fresh_db.session.commit()

    returns = _tick()

    assert returns[flows.id]["dispatch_state"] == "skipped"
    assert _run_of(fresh_db, flows).plan["upstream-runs"][0]["state"] == "passed-over"


def test_a_run_goes_ahead_without_an_inactive_upstream_automation(
    fresh_db, make_automation
):
    """An upstream automation that was never going to run at that time is left out, and the record says so."""
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])
    snapper.active = False
    fresh_db.session.commit()

    returns = _tick()

    assert returns[flows.id]["dispatch_state"] == "queued"
    assert _run_of(fresh_db, flows).plan["upstream-runs"] == [
        {
            "automation": snapper.id,
            "allow-failure": False,
            "due-at": SCHEDULED_AT.isoformat(),
            "run": None,
            "state": "not-scheduled",
        }
    ]


def test_a_run_on_demand_does_not_wait(fresh_db, app, make_automation):
    """Running an automation on demand means running it now, so it does not wait for the automations it depends on."""
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])

    returns = run_automation(flows)

    assert returns["n_jobs"] == 1
    assert app.queues["ingestion"].count == 1


def _run_at(db, automation: Automation, scheduled_at: datetime) -> AutomationRun:
    db.session.expire_all()
    return db.session.scalars(
        select(AutomationRun).where(
            AutomationRun.automation_id == automation.id,
            AutomationRun.scheduled_at == scheduled_at,
        )
    ).one()


def test_an_hourly_run_waits_for_the_upstream_run_due_at_its_own_time(
    fresh_db, app, make_automation
):
    """An hourly automation can wait for one that recurs every 15 minutes, and its run at 01:00 waits for the upstream run due at 01:00."""
    puller = make_automation("Pull meter data", cronstr="*/15 * * * *")
    # Only the upstream run at 01:00 is due, rather than those at 00:15, 00:30 and 00:45, too.
    puller.cursor = datetime(2026, 8, 5, 0, 45, tzinfo=timezone.utc)
    fresh_db.session.commit()
    forecast = make_automation("Forecast", depends_on=[puller])

    returns = _tick()

    assert returns[forecast.id]["dispatch_state"] == "waiting"
    puller_run = _run_at(fresh_db, puller, SCHEDULED_AT)
    upstream = _run_at(fresh_db, forecast, SCHEDULED_AT).plan["upstream-runs"][0]
    assert (upstream["due-at"], upstream["run"]) == (
        SCHEDULED_AT.isoformat(),
        puller_run.id,
    )

    _work(app, puller_run)

    assert _run_at(fresh_db, forecast, SCHEDULED_AT).dispatch_state == "queued"


@pytest.mark.parametrize("upstream_fails", [False, True])
def test_a_quarter_hourly_run_waits_for_the_latest_hourly_upstream_run(
    fresh_db, app, make_automation, failing_value, upstream_fails
):
    """A run every 15 minutes waits for the latest run of an hourly upstream automation.

    Its runs at 01:00 and 01:15 both wait for the upstream run due at 01:00, and both are released once that one ended.
    """
    quarter_past = datetime(2026, 8, 5, 1, 15, tzinfo=timezone.utc)
    puller = make_automation("Pull meter data", value=-1 if upstream_fails else 1)
    forecast = make_automation("Forecast", depends_on=[puller], cronstr="*/15 * * * *")
    forecast.cursor = datetime(2026, 8, 5, 0, 45, tzinfo=timezone.utc)
    fresh_db.session.commit()

    _tick()
    returns = _tick(datetime(2026, 8, 5, 1, 15, 30, tzinfo=timezone.utc))

    assert returns[forecast.id]["dispatch_state"] == "waiting"
    later_run = _run_at(fresh_db, forecast, quarter_past)
    assert later_run.plan["upstream-runs"][0]["due-at"] == SCHEDULED_AT.isoformat()

    _work(app, _run_at(fresh_db, puller, SCHEDULED_AT))

    expected = "skipped" if upstream_fails else "succeeded"
    for scheduled_at in (SCHEDULED_AT, quarter_past):
        run = _run_at(fresh_db, forecast, scheduled_at)
        if not upstream_fails:
            assert run.dispatch_state == "queued"
            _work(app, run)
            run = _run_at(fresh_db, forecast, scheduled_at)
        assert run.execution_state == expected


@pytest.mark.parametrize("upstream_fails", [False, True])
def test_running_a_chain_on_demand(
    fresh_db, app, make_automation, failing_value, upstream_fails
):
    """Run an automation on demand along with what waits for it: each run waits for the one before it, and a failure skips the rest."""
    snapper = make_automation("Snap meter readings", value=-1 if upstream_fails else 1)
    flows = make_automation("Compute flows", depends_on=[snapper])
    totals = make_automation("Sum flows", depends_on=[flows])
    # An inactive automation does not run, and neither does what only waits for it.
    paused = make_automation("Paused", depends_on=[snapper])
    paused.active = False
    make_automation("Waits for paused", depends_on=[paused])
    fresh_db.session.commit()

    returns, dependent_runs = run_automation_chain(snapper, now=TICK)

    assert [run.automation_id for run in dependent_runs] == [flows.id, totals.id]
    assert [run.dispatch_state for run in dependent_runs] == ["waiting", "waiting"]
    snapper_run = fresh_db.session.get(AutomationRun, returns["run_id"])
    assert snapper_run.trigger == "on-demand"
    assert dependent_runs[1].plan["chain-upstream-runs"] == [
        {"automation": flows.id, "run": dependent_runs[0].id}
    ]
    # Their recurrence is left alone.
    assert {snapper.cursor, flows.cursor, totals.cursor} == {CREATED_AT}

    _work(app, snapper_run)
    if upstream_fails:
        for run in dependent_runs:
            assert _run_at(fresh_db, run.automation, SCHEDULED_AT).execution_state == (
                "skipped"
            )
        return
    flows_run = _run_at(fresh_db, flows, SCHEDULED_AT)
    assert flows_run.dispatch_state == "queued"
    assert _run_at(fresh_db, totals, SCHEDULED_AT).dispatch_state == "waiting"
    _work(app, flows_run)
    totals_run = _run_at(fresh_db, totals, SCHEDULED_AT)
    assert totals_run.dispatch_state == "queued"
    _work(app, totals_run)
    assert _run_at(fresh_db, totals, SCHEDULED_AT).execution_state == "succeeded"


def _states(fresh_db, runs: list[AutomationRun]) -> dict[int, tuple[str, str]]:
    fresh_db.session.expire_all()
    return {
        run.automation_id: (run.dispatch_state, run.execution_state) for run in runs
    }


def test_running_with_ascendants_works_its_way_down_and_stops_at_the_automation(
    fresh_db, app, make_automation
):
    """What an automation waits for runs first, what waits for it does not run, and neither does a branch next to it."""
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])
    totals = make_automation("Sum flows", depends_on=[flows])
    make_automation("Sum further", depends_on=[totals])
    make_automation("Side branch", depends_on=[snapper])

    runs, not_running = run_automation_with_ascendants(totals, now=TICK)

    assert [run.automation_id for run in runs] == [snapper.id, flows.id, totals.id]
    assert not_running == []
    assert [run.trigger for run in runs] == ["on-demand"] * 3
    assert _states(fresh_db, runs) == {
        snapper.id: ("queued", "pending"),
        flows.id: ("waiting", "pending"),
        totals.id: ("waiting", "pending"),
    }
    assert {snapper.cursor, flows.cursor, totals.cursor} == {CREATED_AT}
    _work(app, runs[0])
    assert _states(fresh_db, runs)[flows.id][0] == "queued"
    assert _states(fresh_db, runs)[totals.id][0] == "waiting"
    _work(app, runs[1])
    _work(app, runs[2])
    assert _states(fresh_db, runs)[totals.id] == ("queued", "succeeded")


def test_running_with_ascendants_starts_every_branch_and_waits_for_all_of_them(
    fresh_db, app, make_automation
):
    """Several branches lead up to an automation, each starting right away, and it runs once the last of them ended."""
    prices = make_automation("Pull prices")
    meters = make_automation("Pull meters")
    forecast = make_automation("Forecast", depends_on=[prices, meters])

    runs, _ = run_automation_with_ascendants(forecast, now=TICK)

    assert _states(fresh_db, runs) == {
        prices.id: ("queued", "pending"),
        meters.id: ("queued", "pending"),
        forecast.id: ("waiting", "pending"),
    }
    by_automation = {run.automation_id: run for run in runs}
    _work(app, by_automation[prices.id])
    assert _states(fresh_db, runs)[forecast.id][0] == "waiting"
    _work(app, by_automation[meters.id])
    assert _states(fresh_db, runs)[forecast.id][0] == "queued"


@pytest.mark.parametrize("allow_failure", [False, True])
def test_a_failure_above_stops_an_automation_run_with_ascendants(
    fresh_db, app, make_automation, failing_value, allow_failure
):
    """The automation is skipped if what it waits for failed, unless its dependency allows for that."""
    snapper = make_automation("Snap meter readings", value=-1)
    flows = make_automation(
        "Compute flows", depends_on=[snapper], allow_failure=allow_failure
    )

    runs, _ = run_automation_with_ascendants(flows, now=TICK)
    _work(app, runs[0])

    assert _states(fresh_db, runs)[snapper.id][1] == "failed"
    assert _states(fresh_db, runs)[flows.id] == (
        ("queued", "pending") if allow_failure else ("queued", "skipped")
    )


def test_a_branch_can_be_left_out_of_a_run_with_ascendants(
    fresh_db, app, make_automation
):
    """Leaving out an automation takes along what only it needs, and what waits for it goes ahead without it."""
    tariffs = make_automation("Pull tariffs")
    prices = make_automation("Compute prices", depends_on=[tariffs])
    meters = make_automation("Pull meters")
    forecast = make_automation("Forecast", depends_on=[prices, meters])

    runs, not_running = run_automation_with_ascendants(
        forecast, left_out=[prices.id], now=TICK
    )

    assert [run.automation_id for run in runs] == [meters.id, forecast.id]
    assert not_running == []
    _work(app, runs[0])
    assert _states(fresh_db, runs)[forecast.id][0] == "queued"


def test_what_may_not_run_is_reported_and_takes_along_what_is_above_it(
    fresh_db, make_automation
):
    """An automation that is inactive or not allowed does not run, and nothing would use the results of what is above it."""
    tariffs = make_automation("Pull tariffs")
    public = make_automation("Public prices", depends_on=[tariffs])
    paused = make_automation("Paused")
    paused.active = False
    meters = make_automation("Pull meters")
    forecast = make_automation("Forecast", depends_on=[public, paused, meters])

    ascendants, not_running = get_ascendant_automations(
        forecast, may_run=lambda automation: automation.id != public.id
    )

    assert ascendants == [meters]
    assert {automation.id for automation in not_running} == {public.id, paused.id}


def test_an_automation_without_ascendants_just_runs(fresh_db, app, make_automation):
    snapper = make_automation("Snap meter readings")

    runs, _ = run_automation_with_ascendants(snapper, now=TICK)

    assert [run.automation_id for run in runs] == [snapper.id]
    assert _states(fresh_db, runs)[snapper.id][0] == "queued"


def test_the_plan_of_a_run_says_what_will_and_what_will_not_run(
    fresh_db, make_automation
):
    """A plan lists the automations in the order they run, and says why one does not, giving nothing away about one that may not be read."""
    public = make_automation("Public prices")
    meters = make_automation("Pull meters")
    forecast = make_automation("Forecast", depends_on=[public, meters])
    schedule = make_automation("Schedule", depends_on=[forecast])

    steps = plan_automation_chain(
        forecast,
        "ascendants",
        may_read=lambda automation: automation.id != public.id,
        may_run=lambda automation: automation.id != public.id,
    )

    assert steps[0] == {
        "automation": public.id,
        "waits-for": [],
        "will-run": False,
        "reason": "You may not run this automation.",
    }
    assert [(step["automation"], step["will-run"]) for step in steps[1:]] == [
        (meters.id, True),
        (forecast.id, True),
    ]
    assert steps[2]["waits-for"] == [public.id, meters.id]
    assert steps[2]["name"] == "Forecast"

    downwards = plan_automation_chain(
        forecast,
        "dependents",
        may_read=lambda automation: True,
        may_run=lambda automation: automation.id != schedule.id,
    )
    assert [(step["automation"], step["will-run"]) for step in downwards] == [
        (schedule.id, False),
        (forecast.id, True),
    ]


def test_a_chain_run_on_demand_and_a_scheduled_run_keep_apart(
    fresh_db, app, make_automation
):
    """Runs on demand can share a minute with the scheduled runs, and a scheduled run only ever waits for a scheduled upstream run."""
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])
    _tick()

    returns, dependent_runs = run_automation_chain(snapper, now=TICK)
    on_demand_snapper_run = fresh_db.session.get(AutomationRun, returns["run_id"])
    _work(app, on_demand_snapper_run)

    fresh_db.session.expire_all()
    runs = fresh_db.session.scalars(
        select(AutomationRun).where(AutomationRun.automation_id == flows.id)
    ).all()
    states = {run.trigger: run.dispatch_state for run in runs}
    assert states == {"schedule": "waiting", "on-demand": "queued"}


def test_automations_waiting_for_each_other_can_change_their_schedules(
    fresh_db, make_automation
):
    """Runs wait for the latest upstream run due at or before their own time, so either automation can move to another schedule."""
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])

    update_automation(snapper, cronstr="*/15 * * * *")
    update_automation(flows, cronstr="5 * * * *")
    fresh_db.session.commit()

    assert (snapper.cronstr, flows.cronstr) == ("*/15 * * * *", "5 * * * *")
    assert _dependency_ids(fresh_db, flows) == [snapper.id]


def test_cycles_and_self_dependencies_are_refused(fresh_db, make_automation):
    """An automation that ends up waiting for itself would never run."""
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])
    totals = make_automation("Sum flows", depends_on=[flows])

    with pytest.raises(ValidationError) as e:
        update_automation(snapper, dependencies=[{"upstream": totals}])
    assert "waiting for itself" in str(e.value.messages["depends-on"])
    with pytest.raises(ValidationError):
        update_automation(snapper, dependencies=[{"upstream": snapper}])
    fresh_db.session.rollback()
    assert _dependency_ids(fresh_db, snapper) == []


def test_deleting_an_upstream_automation_drops_the_dependency(
    fresh_db, make_automation
):
    snapper = make_automation("Snap meter readings")
    flows = make_automation("Compute flows", depends_on=[snapper])

    fresh_db.session.delete(snapper)
    fresh_db.session.commit()

    assert _dependency_ids(fresh_db, flows) == []


def _dependency_ids(db, automation: Automation) -> list[int]:
    db.session.expire_all()
    return [
        dependency.upstream_id
        for dependency in db.session.get(Automation, automation.id).dependencies
    ]
