import pytest
from types import SimpleNamespace

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
    # NB click reports the offending value; once it reports the validation message
    # instead (see PR #2303), the cron string's own error text shows up here.
    assert "Invalid value" in result.output


@pytest.mark.parametrize(
    ("yaml_start", "expected_start"),
    (
        ("2026-07-31", "2026-07-31"),
        ("2026-07-31T06:00:00+01:00", "2026-07-31T06:00:00+01:00"),
    ),
)
def test_add_automation_normalizes_yaml_dates(
    app,
    fresh_db,
    setup_dummy_data,
    tmp_path,
    yaml_start,
    expected_start,
):
    from flexmeasures.cli.data_add import add_automation

    parameters_file = tmp_path / "parameters.yaml"
    parameters_file.write_text(f"start: {yaml_start}\n")
    result = app.test_cli_runner().invoke(
        add_automation,
        [
            "--asset",
            "1",
            "--name",
            "YAML dates",
            "--cron",
            "0 6 * * *",
            "--parameters",
            str(parameters_file),
            "--sensor",
            str(setup_dummy_data[0]),
        ],
    )

    assert result.exit_code == 0, result.output
    automation = fresh_db.session.scalars(select(Automation)).one()
    assert automation.parameters["start"] == expected_start


@pytest.mark.parametrize("option_name", ("--config", "--parameters"))
def test_add_automation_accepts_empty_yaml_file(
    app, fresh_db, setup_dummy_data, tmp_path, option_name
):
    from flexmeasures.cli.data_add import add_automation

    empty_file = tmp_path / "empty.yaml"
    empty_file.write_text("")
    result = app.test_cli_runner().invoke(
        add_automation,
        [
            "--asset",
            "1",
            "--name",
            "Empty YAML",
            "--cron",
            "0 6 * * *",
            option_name,
            str(empty_file),
            "--sensor",
            str(setup_dummy_data[0]),
        ],
    )

    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("option_name", ("--config", "--parameters"))
def test_add_automation_rejects_non_object_yaml_file(
    app, fresh_db, setup_dummy_data, tmp_path, option_name
):
    from flexmeasures.cli.data_add import add_automation

    list_file = tmp_path / "list.yaml"
    list_file.write_text("- not\n- an\n- object\n")
    result = app.test_cli_runner().invoke(
        add_automation,
        [
            "--asset",
            "1",
            "--name",
            "Invalid YAML",
            "--cron",
            "0 6 * * *",
            option_name,
            str(list_file),
            "--sensor",
            str(setup_dummy_data[0]),
        ],
    )

    assert result.exit_code == 2, result.output
    assert "must contain a YAML or JSON object at the top level" in result.output
    assert "Traceback" not in result.output


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
    assert result.output.count("already attempted") == 2, result.output
    assert len(app.queues["forecasting"].jobs) == n_jobs

    # inactive automations are not due
    for automation in automations:
        automation.active = False
    fresh_db.session.commit()
    app.redis_connection.flushdb()
    result = runner.invoke(run_automations)
    assert "No automations due" in result.output, result.output


def test_failed_automation_attempt_is_not_retried(app, clean_redis, mocker):
    """A failure after partial queueing must not duplicate that work on retry."""
    from flexmeasures.cli.jobs import run_automations

    automation = SimpleNamespace(id=42, name="Partial run", asset_id=1)
    mocker.patch("flexmeasures.cli.jobs.get_due_automations", return_value=[automation])

    def queue_then_fail(_automation):
        app.queues["forecasting"].enqueue("flexmeasures.utils.time_utils.server_now")
        raise RuntimeError("failed after queueing")

    mocker.patch("flexmeasures.cli.jobs.run_automation", side_effect=queue_then_fail)
    runner = app.test_cli_runner()

    first_result = runner.invoke(run_automations)
    assert first_result.exit_code == 1, first_result.output
    assert "failed after queueing" in first_result.output
    assert app.queues["forecasting"].count == 1

    retry_result = runner.invoke(run_automations)
    assert retry_result.exit_code == 0, retry_result.output
    assert "already attempted" in retry_result.output
    assert "Skipping to avoid duplicate jobs" in retry_result.output
    assert app.queues["forecasting"].count == 1
