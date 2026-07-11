"""Integration tests for running automations (service level)."""

from __future__ import annotations

import pytest
from rq.job import Job

from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.services.automations import run_automation


@pytest.fixture(scope="function")
def keep_scheduling_queue_empty(app):
    app.queues["scheduling"].empty()
    yield
    app.queues["scheduling"].empty()


def test_run_schedule_automation(
    db, app, add_battery_assets, add_market_prices, keep_scheduling_queue_empty
):
    """A schedules automation queues a scheduling job carrying trigger meta data."""
    battery = add_battery_assets["Test battery"]
    message = message_for_trigger_schedule()
    flex_model = message.pop("flex-model")
    flex_model["sensor"] = battery.sensors[0].id

    automation = Automation(
        asset_id=battery.id,
        type="schedules",
        name="Nightly schedules",
        cronstr="0 0 * * *",
        parameters={**message, "flex-model": [flex_model]},
    )
    db.session.add(automation)
    db.session.flush()

    returns = run_automation(automation)
    assert returns["n_jobs"] == 1

    job = Job.fetch(returns["job_id"], connection=app.queues["scheduling"].connection)
    assert job.meta["trigger"] == {
        "origin": "automation",
        "automation_id": automation.id,
    }

    # trigger provenance must not affect job identity: the same schedule request
    # from another origin dedupes onto the same job (via the job cache)
    returns_2 = run_automation(automation)
    assert returns_2["job_id"] == returns["job_id"]
