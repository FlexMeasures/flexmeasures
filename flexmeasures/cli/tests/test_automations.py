from datetime import timedelta

import pytest
import yaml

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


def test_prepare_report_parameters(app):
    """Report start/end resolve per run: from Pandas offsets, or defaulting to the last cron period."""
    import pandas as pd

    from flexmeasures.data.services.automations import prepare_report_parameters
    from flexmeasures.utils.time_utils import get_timezone

    now = pd.Timestamp("2026-07-11T14:00:00+02:00")
    # without an output sensor, offsets resolve in the platform timezone
    local_now = now.tz_convert(get_timezone())

    # default: the last cron period (hourly cron -> the previous hour)
    message = prepare_report_parameters({}, "0 * * * *", now=now)
    assert pd.Timestamp(message["start"]) == now - pd.Timedelta(hours=1)
    assert pd.Timestamp(message["end"]) == now

    # with a known actual last run, the window starts there instead
    app.redis_connection.set("automation-last-run:1234", "2026-07-11T09:30:00+02:00")
    try:
        message = prepare_report_parameters(
            {}, "0 * * * *", now=now, automation_id=1234
        )
        assert pd.Timestamp(message["start"]) == pd.Timestamp(
            "2026-07-11T09:30:00+02:00"
        )
        assert pd.Timestamp(message["end"]) == now
        # an unknown automation id still falls back to the last cron period
        message = prepare_report_parameters(
            {}, "0 * * * *", now=now, automation_id=5678
        )
        assert pd.Timestamp(message["start"]) == now - pd.Timedelta(hours=1)
    finally:
        app.redis_connection.delete("automation-last-run:1234")

    # offsets applied to the run time; "DB" floors to the day begin
    message = prepare_report_parameters(
        {"start-offset": "-1D,DB", "end-offset": "DB"}, "0 1 * * *", now=now
    )
    assert (
        pd.Timestamp(message["start"]) == (local_now - pd.Timedelta(days=1)).normalize()
    )
    assert pd.Timestamp(message["end"]) == local_now.normalize()
    assert "start-offset" not in message and "end-offset" not in message

    # absolute datetimes pass through untouched
    message = prepare_report_parameters(
        {"start": "2026-01-01T00:00:00+01:00", "end": "2026-01-02T00:00:00+01:00"},
        "0 1 * * *",
        now=now,
    )
    assert pd.Timestamp(message["start"]) == pd.Timestamp("2026-01-01T00:00:00+01:00")
    assert pd.Timestamp(message["end"]) == pd.Timestamp("2026-01-02T00:00:00+01:00")


def _report_automation_cli_input(
    tmp_path, sensor1_id, sensor2_id, report_sensor_id, parameters_extra=None
):
    """CLI input for a report automation using a simple PandasReporter aggregation."""
    reporter_config = dict(
        required_input=[{"name": "sensor_1"}, {"name": "sensor_2"}],
        required_output=[{"name": "df_agg"}],
        transformations=[
            dict(
                df_input="sensor_1",
                method="add",
                args=["@sensor_2"],
                df_output="df_agg",
            ),
            dict(method="resample_events", args=["2h"]),
        ],
    )
    parameters = dict(
        input=[
            dict(name="sensor_1", sensor=sensor1_id),
            dict(name="sensor_2", sensor=sensor2_id),
        ],
        output=[dict(name="df_agg", sensor=report_sensor_id)],
        **(parameters_extra or {}),
    )
    config_file = tmp_path / "reporter_config.yml"
    config_file.write_text(yaml.dump(reporter_config))
    parameters_file = tmp_path / "parameters.yml"
    parameters_file.write_text(yaml.dump(parameters))
    return [
        "--asset", "1",
        "--name", "Aggregation report",
        "--cron", "0 1 * * *",
        "--type", "reports",
        "--reporter", "PandasReporter",
        "--config", str(config_file),
        "--parameters", str(parameters_file),
    ]  # fmt: skip


def test_add_report_automation(app, fresh_db, setup_dummy_data, tmp_path):
    """Create a reports automation; the reporter config lands on a data source."""
    from flexmeasures.cli.data_add import add_automation

    sensor1_id, sensor2_id, report_sensor_id, _ = setup_dummy_data
    runner = app.test_cli_runner()
    result = runner.invoke(
        add_automation,
        _report_automation_cli_input(
            tmp_path,
            sensor1_id,
            sensor2_id,
            report_sensor_id,
            parameters_extra={"start-offset": "-1D,DB", "end-offset": "DB"},
        ),
    )
    assert "Successfully created" in result.output, result.output
    automation = fresh_db.session.execute(select(Automation)).scalar_one()
    assert automation.type == "reports"
    assert automation.generator is not None
    assert automation.generator.model == "PandasReporter"
    assert automation.parameters["start-offset"] == "-1D,DB"

    # a reports automation without a reporter is rejected
    result = runner.invoke(
        add_automation,
        [
            "--asset", "1",
            "--name", "No reporter",
            "--cron", "0 1 * * *",
            "--type", "reports",
        ],
    )  # fmt: skip
    assert result.exit_code != 0
    assert "reporter is required" in result.output


def test_run_report_automation(app, fresh_db, setup_dummy_data, clean_redis, tmp_path):
    """A due reports automation queues a reporting job; a worker computes and saves the report."""
    from flexmeasures.cli.data_add import add_automation
    from flexmeasures.cli.jobs import run_automations
    from flexmeasures.data.models.time_series import Sensor
    from flexmeasures.utils.job_utils import work_on_rq

    sensor1_id, sensor2_id, report_sensor_id, _ = setup_dummy_data
    runner = app.test_cli_runner()
    cli_input = _report_automation_cli_input(
        tmp_path,
        sensor1_id,
        sensor2_id,
        report_sensor_id,
        # the dummy data lives in April 2023, so use an absolute reporting window
        parameters_extra={
            "start": "2023-04-10T00:00:00+00:00",
            "end": "2023-04-10T10:00:00+00:00",
        },
    )
    cli_input[cli_input.index("0 1 * * *")] = "* * * * *"  # due every minute
    result = runner.invoke(add_automation, cli_input)
    assert "Successfully created" in result.output, result.output
    automation = fresh_db.session.execute(select(Automation)).scalar_one()

    result = runner.invoke(run_automations)
    assert result.exit_code == 0, result.output
    assert "queued 1 reporting job(s)" in result.output, result.output

    # the queued job recorded how it was created
    jobs = app.queues["reporting"].jobs
    assert len(jobs) == 1
    assert jobs[0].meta["trigger"] == {
        "origin": "automation",
        "automation_id": automation.id,
    }

    # process the job and check the report got saved
    work_on_rq(app.queues["reporting"])
    report_sensor = fresh_db.session.get(Sensor, report_sensor_id)
    stored_report = report_sensor.search_beliefs(
        event_starts_after="2023-04-10T00:00:00+00:00",
        event_ends_before="2023-04-10T10:00:00+00:00",
    )
    assert (stored_report.values.T == [1, 2 + 3, 4 + 5, 6 + 7, 8 + 9]).all()


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
    # the run got recorded (used e.g. to anchor default report windows)
    for automation in automations:
        assert app.redis_connection.get(f"automation-last-run:{automation.id}")
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
