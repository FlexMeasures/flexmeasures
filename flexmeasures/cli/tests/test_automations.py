from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from sqlalchemy import select

from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.services.automations import floor_to_minute
from flexmeasures.utils.time_utils import server_now
from flexmeasures.cli.tests.utils import to_flags

LAST_TICK_KEY = "automation-runner:last-tick"


@pytest.fixture(scope="function")
def clean_redis(app):
    app.redis_connection.flushdb()
    yield
    app.redis_connection.flushdb()


def add_automation(app, name: str, cron: str, sensor_id: int):
    """Create an automation on asset 1 through the CLI."""
    from flexmeasures.cli.data_add import add_automation as add_automation_command

    runner = app.test_cli_runner()
    cli_input = {"asset": 1, "name": name, "cron": cron, "sensor": sensor_id}
    result = runner.invoke(add_automation_command, to_flags(cli_input))
    assert "Successfully created" in result.output, result.output


def get_last_tick(app) -> datetime | None:
    """Read the runner's last processed minute from Redis."""
    value = app.redis_connection.get(LAST_TICK_KEY)
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode()
    return datetime.fromisoformat(value)


def daily_cron(minute_in_time: datetime) -> str:
    """Cron string matching (daily) the given minute, in the FLEXMEASURES_TIMEZONE."""
    minute_in_time = floor_to_minute(minute_in_time)
    return f"{minute_in_time.minute} {minute_in_time.hour} * * *"


def test_add_edit_delete_automation(app, fresh_db, setup_dummy_data):
    """Roundtrip: create an automation, edit it, then delete it, checking the audit log along the way."""
    from flexmeasures.cli.data_add import add_automation
    from flexmeasures.cli.data_edit import edit_automation
    from flexmeasures.cli.data_delete import delete_automation

    sensor_id = setup_dummy_data[0]
    runner = app.test_cli_runner()

    # add
    cli_input = {
        "asset": 1,
        "name": "Test forecasts",
        "cron": "0 6 * * *",
        "sensor": sensor_id,
    }
    result = runner.invoke(add_automation, to_flags(cli_input))
    assert "Successfully created" in result.output, result.output
    automation = fresh_db.session.execute(
        select(Automation).filter_by(name="Test forecasts")
    ).scalar_one_or_none()
    assert automation is not None
    assert automation.active is True
    assert automation.type == "forecasts"
    assert automation.cronstr == "0 6 * * *"
    # CLI option values are stored as provided (strings); they are coerced by the schema when the automation runs
    assert automation.parameters == {"sensor": str(sensor_id)}
    assert automation.generator is not None
    assert automation.generator.model == "TrainPredictPipeline"
    assert fresh_db.session.execute(
        select(AssetAuditLog).filter(AssetAuditLog.event.like("Created automation%"))
    ).scalar_one_or_none()

    # edit
    result = runner.invoke(
        edit_automation,
        ["--id", automation.id, "--name", "Renamed", "--deactivate"],
    )
    assert "Successfully updated" in result.output, result.output
    assert automation.name == "Renamed"
    assert automation.active is False
    assert fresh_db.session.execute(
        select(AssetAuditLog).filter(AssetAuditLog.event.like("Updated automation%"))
    ).scalar_one_or_none()

    # delete
    result = runner.invoke(delete_automation, ["--id", automation.id, "--force"])
    assert "Successfully deleted" in result.output, result.output
    assert fresh_db.session.execute(select(Automation)).scalar_one_or_none() is None
    assert fresh_db.session.execute(
        select(AssetAuditLog).filter(AssetAuditLog.event.like("Deleted automation%"))
    ).scalar_one_or_none()


def test_add_automation_invalid_cron(app, fresh_db, setup_dummy_data):
    from flexmeasures.cli.data_add import add_automation

    sensor_id = setup_dummy_data[0]
    runner = app.test_cli_runner()
    cli_input = {
        "asset": 1,
        "name": "Test forecasts",
        "cron": "not a cron string",
        "sensor": sensor_id,
    }
    result = runner.invoke(add_automation, to_flags(cli_input))
    assert result.exit_code != 0
    # NB click reports the offending value; once it reports the validation message
    # instead (see PR #2303), the cron string's own error text shows up here.
    assert "Invalid value" in result.output


def test_run_automations(app, fresh_db, setup_dummy_data, clean_redis):
    """Active automations due this minute queue forecasting jobs (with trigger meta data); inactive ones do not.

    We use two automations with the same forecaster config (thus sharing a generator data source),
    to make sure one automation's run does not pollute the other's.
    """
    from flexmeasures.cli.data_add import add_automation
    from flexmeasures.cli.jobs import run_automations

    sensor1_id, sensor2_id = setup_dummy_data[0], setup_dummy_data[1]
    runner = app.test_cli_runner()
    for name, sensor_id in [
        ("Every minute", sensor1_id),
        ("Also every minute", sensor2_id),
    ]:
        cli_input = {
            "asset": 1,
            "name": name,
            "cron": "* * * * *",  # due every minute
            "sensor": sensor_id,
        }
        result = runner.invoke(add_automation, to_flags(cli_input))
        assert "Successfully created" in result.output, result.output
    automations = fresh_db.session.scalars(select(Automation)).all()
    assert automations[0].generator_id == automations[1].generator_id

    result = runner.invoke(run_automations)
    assert result.exit_code == 0, result.output
    assert result.output.count("queued") == 2, result.output

    # check the queued jobs recorded how they were created
    jobs = app.queues["forecasting"].jobs
    assert len(jobs) > 0
    automation_ids = {automation.id for automation in automations}
    assert all(
        job.meta["trigger"]["origin"] == "automation"
        and job.meta["trigger"]["automation_id"] in automation_ids
        for job in jobs
    )
    # running again within the same minute does not queue jobs twice
    n_jobs = len(jobs)
    result = runner.invoke(run_automations)
    assert result.output.count("already ran") == 2, result.output
    assert len(app.queues["forecasting"].jobs) == n_jobs

    # inactive automations are not due
    for automation in automations:
        automation.active = False
    fresh_db.session.commit()
    app.redis_connection.flushdb()
    result = runner.invoke(run_automations)
    assert "No automations due" in result.output, result.output


def test_run_automations_catchup(app, fresh_db, setup_dummy_data, clean_redis):
    """An automation due in a missed minute (but not this minute) runs when catching up."""
    from flexmeasures.cli.jobs import run_automations

    now = floor_to_minute(server_now())
    # due 5 minutes ago, i.e. within the missed window, but not due this minute
    add_automation(
        app, "Catch me up", daily_cron(now - timedelta(minutes=5)), setup_dummy_data[0]
    )
    app.redis_connection.set(
        LAST_TICK_KEY, floor_to_minute(now - timedelta(minutes=10)).isoformat()
    )

    runner = app.test_cli_runner()
    result = runner.invoke(run_automations)
    assert result.exit_code == 0, result.output
    assert "Catching up" in result.output, result.output
    assert result.output.count("queued") == 1, result.output
    n_jobs = len(app.queues["forecasting"].jobs)
    assert n_jobs > 0

    # the last tick advanced to the current minute, so the next invocation has nothing to do
    assert get_last_tick(app) >= now
    result = runner.invoke(run_automations)
    assert "No automations due" in result.output, result.output
    assert len(app.queues["forecasting"].jobs) == n_jobs


def test_run_automations_catchup_once_per_invocation(
    app, fresh_db, setup_dummy_data, clean_redis
):
    """An automation due in every missed minute still runs only once per invocation."""
    from flexmeasures.cli.jobs import run_automations

    now = floor_to_minute(server_now())
    add_automation(app, "Every minute", "* * * * *", setup_dummy_data[0])
    app.redis_connection.set(
        LAST_TICK_KEY, floor_to_minute(now - timedelta(minutes=10)).isoformat()
    )

    runner = app.test_cli_runner()
    result = runner.invoke(run_automations)
    assert result.exit_code == 0, result.output
    # due in all 11 minutes of the window, but queued only once
    assert result.output.count("queued") == 1, result.output


def test_run_automations_max_catchup(app, fresh_db, setup_dummy_data, clean_redis):
    """Minutes missed longer ago than --max-catchup are ignored."""
    from flexmeasures.cli.jobs import run_automations

    now = floor_to_minute(server_now())
    add_automation(
        app,
        "Too long ago",
        daily_cron(now - timedelta(minutes=20)),
        setup_dummy_data[0],
    )
    add_automation(
        app,
        "Recently missed",
        daily_cron(now - timedelta(minutes=5)),
        setup_dummy_data[1],
    )
    app.redis_connection.set(
        LAST_TICK_KEY, floor_to_minute(now - timedelta(minutes=30)).isoformat()
    )

    runner = app.test_cli_runner()
    result = runner.invoke(run_automations, ["--max-catchup", "10"])
    assert result.exit_code == 0, result.output
    assert result.output.count("queued") == 1, result.output
    assert "Recently missed" in result.output, result.output
    assert "Too long ago" not in result.output, result.output

    # with catch-up disabled, only the current minute is processed
    app.redis_connection.flushdb()
    app.redis_connection.set(
        LAST_TICK_KEY, floor_to_minute(now - timedelta(minutes=30)).isoformat()
    )
    result = runner.invoke(run_automations, ["--max-catchup", "0"])
    assert "No automations due" in result.output, result.output


def test_run_automations_first_run(app, fresh_db, setup_dummy_data, clean_redis):
    """Without a last tick recorded, only the current minute is processed."""
    from flexmeasures.cli.jobs import run_automations

    now = floor_to_minute(server_now())
    # due 5 minutes ago, but there is no last tick, so there is no window to catch up on
    add_automation(
        app,
        "Missed before first run",
        daily_cron(now - timedelta(minutes=5)),
        setup_dummy_data[0],
    )
    assert app.redis_connection.get(LAST_TICK_KEY) is None

    runner = app.test_cli_runner()
    result = runner.invoke(run_automations)
    assert result.exit_code == 0, result.output
    assert "No automations due" in result.output, result.output
    # the first run recorded a last tick, so future invocations can catch up
    assert get_last_tick(app) >= now
