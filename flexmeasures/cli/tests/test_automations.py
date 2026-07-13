from datetime import timedelta

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
    # NB click reports the offending value; once it reports the validation message
    # instead (see PR #2303), the cron string's own error text shows up here.
    assert "Invalid value" in result.output


def test_add_schedule_automation(app, fresh_db, setup_dummy_data, tmp_path):
    """Create a schedules automation; parameters are validated as a schedule trigger message."""
    from flexmeasures.cli.data_add import add_automation

    runner = app.test_cli_runner()

    # invalid parameters (unknown field) are rejected
    parameters_file = tmp_path / "parameters.yml"
    parameters_file.write_text("not-a-trigger-field: 1\n")
    result = runner.invoke(
        add_automation,
        [
            "--asset", "1",
            "--name", "Bad schedules",
            "--cron", "0 * * * *",
            "--type", "schedules",
            "--parameters", str(parameters_file),
        ],
    )  # fmt: skip
    assert result.exit_code != 0
    assert "Invalid schedule parameters" in result.output

    # minimal valid parameters (flex config can live on the asset)
    parameters_file.write_text('duration: "PT12H"\n')
    result = runner.invoke(
        add_automation,
        [
            "--asset", "1",
            "--name", "Half-day schedules",
            "--cron", "0 * * * *",
            "--type", "schedules",
            "--parameters", str(parameters_file),
        ],
    )  # fmt: skip
    assert "Successfully created" in result.output, result.output
    automation = fresh_db.session.execute(
        select(Automation).filter_by(name="Half-day schedules")
    ).scalar_one()
    assert automation.type == "schedules"
    assert automation.generator_id is None
    assert automation.parameters == {"duration": "PT12H"}

    # a fixed start draws a warning
    parameters_file.write_text('start: "2026-01-01T00:00:00+01:00"\n')
    result = runner.invoke(
        add_automation,
        [
            "--asset", "1",
            "--name", "Fixed-start schedules",
            "--cron", "0 * * * *",
            "--type", "schedules",
            "--parameters", str(parameters_file),
        ],
    )  # fmt: skip
    assert "Successfully created" in result.output, result.output
    assert "each run will compute the same period" in result.output


def test_run_schedule_automation_dispatch(app, fresh_db, setup_dummy_data, monkeypatch):
    """Running a schedules automation queues a scheduling job with trigger meta data.

    We monkeypatch the job creator to avoid needing a fully schedulable asset here.
    """
    from flexmeasures.data.models.generic_assets import GenericAsset
    from flexmeasures.data.services import scheduling
    from flexmeasures.data.services.automations import run_automation
    from flexmeasures.utils.time_utils import server_now

    asset = fresh_db.session.get(GenericAsset, 1)
    automation = Automation(
        asset_id=asset.id,
        type="schedules",
        name="Test schedules",
        cronstr="0 * * * *",
        parameters={"duration": "PT12H", "resolution": "PT15M"},
    )
    fresh_db.session.add(automation)
    fresh_db.session.flush()

    calls = {}

    def fake_create_simultaneous_scheduling_job(asset, **kwargs):
        calls["asset"] = asset
        calls["kwargs"] = kwargs

        class FakeJob:
            id = "fake-job-id"

        return FakeJob()

    monkeypatch.setattr(
        scheduling,
        "create_simultaneous_scheduling_job",
        fake_create_simultaneous_scheduling_job,
    )

    returns = run_automation(automation)
    assert returns == {"job_id": "fake-job-id", "n_jobs": 1}
    assert calls["asset"].id == asset.id
    assert calls["kwargs"]["trigger"] == {
        "origin": "automation",
        "automation_id": automation.id,
    }
    # start defaulted to (roughly) now, floored to the 15-minute resolution
    start = calls["kwargs"]["start"]
    assert start.minute % 15 == 0
    assert abs((server_now() - start).total_seconds()) < 16 * 60
    assert calls["kwargs"]["end"] - start == timedelta(hours=12)


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
