import pytest

from sqlalchemy import select

from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.automations import Automation
from flexmeasures.cli.tests.utils import to_flags


@pytest.fixture(scope="function")
def clean_redis(app):
    app.redis_connection.flushdb()
    yield
    app.redis_connection.flushdb()


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
    assert "Invalid value for '--cron'" in result.output


def test_run_automations(app, fresh_db, setup_dummy_data, clean_redis):
    """An active automation due this minute queues forecasting jobs (with trigger meta data); an inactive one does not."""
    from flexmeasures.cli.data_add import add_automation
    from flexmeasures.cli.jobs import run_automations

    sensor_id = setup_dummy_data[0]
    runner = app.test_cli_runner()
    cli_input = {
        "asset": 1,
        "name": "Every minute",
        "cron": "* * * * *",  # due every minute
        "sensor": sensor_id,
    }
    result = runner.invoke(add_automation, to_flags(cli_input))
    assert "Successfully created" in result.output, result.output
    automation = fresh_db.session.execute(select(Automation)).scalar_one()

    result = runner.invoke(run_automations)
    assert "queued" in result.output, result.output

    # check the queued jobs recorded how they were created
    jobs = app.queues["forecasting"].jobs
    assert len(jobs) > 0
    assert all(
        job.meta["trigger"] == {"origin": "automation", "automation_id": automation.id}
        for job in jobs
    )

    # running again within the same minute does not queue jobs twice
    n_jobs = len(jobs)
    result = runner.invoke(run_automations)
    assert "already ran" in result.output, result.output
    assert len(app.queues["forecasting"].jobs) == n_jobs

    # an inactive automation is not due
    automation.active = False
    fresh_db.session.commit()
    app.redis_connection.flushdb()
    result = runner.invoke(run_automations)
    assert "No automations due" in result.output, result.output
