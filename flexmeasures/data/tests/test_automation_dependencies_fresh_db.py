"""Automations that wait for the runs of other automations: validation, and how the runner holds, releases and skips their runs."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from marshmallow import ValidationError
from rq.job import Job
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
