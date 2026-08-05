from datetime import datetime, timedelta

import pytest

from sqlalchemy import select

from flexmeasures import Sensor
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.automations import Automation
from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.utils.time_utils import get_timezone


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


def test_add_automation_default_cron(app, fresh_db, setup_dummy_data):
    """Without --cron, an automation recurs daily."""
    from flexmeasures.cli.data_add import add_automation
    from flexmeasures.data.services.automations import get_due_automations

    sensor_id = setup_dummy_data[0]
    runner = app.test_cli_runner()
    result = runner.invoke(
        add_automation,
        to_flags({"asset": 1, "name": "Daily forecasts", "sensor": sensor_id}),
    )
    assert "Successfully created" in result.output, result.output
    automation = fresh_db.session.execute(
        select(Automation).filter_by(name="Daily forecasts")
    ).scalar_one()
    assert automation.cronstr == "0 0 * * *"

    # due at midnight in the server's timezone, and not an hour later
    midnight = get_timezone().localize(datetime(2026, 7, 11, 0, 0))
    assert [a.id for a in get_due_automations(midnight)] == [automation.id]
    assert get_due_automations(midnight + timedelta(hours=1)) == []


def test_add_automation_source_conflicts_with_forecaster(
    app, fresh_db, setup_dummy_data
):
    """--source already determines the forecaster and its config, so combining them fails."""
    from flexmeasures.cli.data_add import add_automation

    sensor_id = setup_dummy_data[0]
    runner = app.test_cli_runner()
    # first create an automation, so that a data source with a forecaster config exists
    result = runner.invoke(
        add_automation,
        to_flags({"asset": 1, "name": "First", "sensor": sensor_id}),
    )
    assert "Successfully created" in result.output, result.output
    source_id = (
        fresh_db.session.execute(select(Automation).filter_by(name="First"))
        .scalar_one()
        .generator_id
    )

    result = runner.invoke(
        add_automation,
        to_flags(
            {
                "asset": 1,
                "name": "Second",
                "sensor": sensor_id,
                "source": source_id,
                "forecaster": "TrainPredictPipeline",
            }
        ),
    )
    assert result.exit_code != 0
    assert "--forecaster cannot be combined with --source" in result.output

    # without the conflicting option, the same data source is simply reused
    result = runner.invoke(
        add_automation,
        to_flags(
            {"asset": 1, "name": "Second", "sensor": sensor_id, "source": source_id}
        ),
    )
    assert "Successfully created" in result.output, result.output
    assert (
        fresh_db.session.execute(select(Automation).filter_by(name="Second"))
        .scalar_one()
        .generator_id
        == source_id
    )


def test_automation_sensors(app, fresh_db, setup_dummy_data):
    """An automation knows which sensors it reads from and writes to."""
    from flexmeasures.cli.data_add import add_automation
    from flexmeasures.data.services.automations import get_automations_feeding_sensor

    sensor_id, regressor_id = setup_dummy_data[0], setup_dummy_data[1]
    runner = app.test_cli_runner()
    result = runner.invoke(
        add_automation,
        to_flags(
            {
                "asset": 1,
                "name": "Test forecasts",
                "sensor": sensor_id,
                "regressors": regressor_id,
            }
        ),
    )
    assert "Successfully created" in result.output, result.output
    automation = fresh_db.session.execute(
        select(Automation).filter_by(name="Test forecasts")
    ).scalar_one()
    assert [sensor.id for sensor in automation.output_sensors] == [sensor_id]
    assert sorted(sensor.id for sensor in automation.input_sensors) == sorted(
        [sensor_id, regressor_id]
    )

    sensor = fresh_db.session.get(Sensor, sensor_id)
    assert [a.id for a in get_automations_feeding_sensor(sensor)] == [automation.id]


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
