import re

import pytest
import yaml
from sqlalchemy import func, select

from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.user import Account, User
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.time_series import Sensor, TimedBelief

from flexmeasures.cli.tests.utils import check_command_ran_without_error
from flexmeasures.data.models.data_sources import DataSource


def test_add_forecast(app, db, setup_dummy_data):
    from flexmeasures.cli.data_add import add_forecast

    sensor_id, *_ = setup_dummy_data
    cli_input = {
        "sensor": sensor_id,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(add_forecast, to_flags(cli_input))
    assert result.exit_code == 0, result.output


def _count_beliefs(db, sensor_id: int) -> int:
    """Count the beliefs recorded on the given sensor."""
    return db.session.scalar(
        select(func.count()).select_from(TimedBelief).filter_by(sensor_id=sensor_id)
    )


def _count_sources(db) -> int:
    """Count the data sources on record."""
    return db.session.scalar(select(func.count()).select_from(DataSource))


def test_add_forecast_dry_run_saves_no_beliefs(app, db, setup_dummy_data):
    """A dry run reports the forecast it computed, without recording any belief."""
    from flexmeasures.cli.data_add import add_forecast

    sensor_id, *_ = setup_dummy_data
    runner = app.test_cli_runner()

    # Earlier dry runs in this module may have flushed a data source without committing it, and the rollback below would discard that too.
    db.session.rollback()
    beliefs_before_dry_run = _count_beliefs(db, sensor_id)
    sources_before_dry_run = _count_sources(db)
    result = runner.invoke(
        add_forecast, to_flags({"sensor": sensor_id}) + ["--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert (
        "Not saving forecasts to the database (because of --dry-run)" in result.output
    )
    assert f"for sensor `sensor 1` (ID {sensor_id})" in result.output

    # The source is named, but never by ID: a source this run had to create is rolled back on the way out,
    # so any ID reported for it would belong to nothing by the time the command returns.
    assert "to be recorded under data source `" in result.output
    assert (
        "data source `FlexMeasures's TrainPredictPipeline forecaster` (ID"
        not in result.output
    )

    # The forecaster's data source is flushed, because the dry run reports which source it would have recorded under,
    # but it is never committed, so no more of it survives the session than of the beliefs.
    db.session.rollback()
    assert _count_beliefs(db, sensor_id) == beliefs_before_dry_run
    assert _count_sources(db) == sources_before_dry_run

    # A normal run does record beliefs, so the dry run really skipped that step
    result = runner.invoke(add_forecast, to_flags({"sensor": sensor_id}))
    assert result.exit_code == 0, result.output
    assert "Successfully created" in result.output
    assert _count_beliefs(db, sensor_id) > beliefs_before_dry_run

    # A run that commits does name its data source by ID, and that ID is one you can look up.
    reported_source_id = int(
        re.search(r"under data source `.*` \(ID (\d+)\)", result.output).group(1)
    )
    assert (
        db.session.get(DataSource, reported_source_id).type == "forecaster"
    ), f"the source ID reported on a committed run should exist: {result.output}"


def test_add_forecast_dry_run_reports_an_empty_forecast(
    app, db, setup_dummy_data, monkeypatch
):
    """A dry run that computes no beliefs at all still reports, rather than crashing on an empty frame."""
    import timely_beliefs as tb

    from flexmeasures.cli.data_add import add_forecast
    from flexmeasures.data.models.forecasting.pipelines import TrainPredictPipeline

    sensor_id, *_ = setup_dummy_data
    sensor = db.session.get(Sensor, sensor_id)

    def compute_nothing(self, *args, **kwargs):
        self._parameters = {"sensor": sensor, "sensor_to_save": sensor}
        return [{"data": tb.BeliefsDataFrame(sensor=sensor), "sensor": sensor}]

    monkeypatch.setattr(TrainPredictPipeline, "compute", compute_nothing)

    runner = app.test_cli_runner()
    result = runner.invoke(
        add_forecast, to_flags({"sensor": sensor_id}) + ["--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert "0 forecast beliefs across 0 unique belief times" in result.output
    assert "covering events from" not in result.output


def test_add_forecast_rejects_dry_run_as_job(app, setup_dummy_data):
    """A dry run cannot be queued, because its results would never reach the user."""
    from flexmeasures.cli.data_add import add_forecast

    sensor_id, *_ = setup_dummy_data
    runner = app.test_cli_runner()
    result = runner.invoke(
        add_forecast, to_flags({"sensor": sensor_id}) + ["--dry-run", "--as-job"]
    )

    assert result.exit_code == 1
    assert "The --as-job flag cannot be combined with --dry-run" in result.output


def test_add_forecast_rejects_dry_run_as_job_from_parameters_file(
    app, setup_dummy_data, tmp_path
):
    """A dry run set in a parameters file is rejected in combination with --as-job, too."""
    from flexmeasures.cli.data_add import add_forecast

    sensor_id, *_ = setup_dummy_data
    parameters_file = tmp_path / "parameters.yml"
    parameters_file.write_text(yaml.safe_dump({"dry-run": True}))
    runner = app.test_cli_runner()
    result = runner.invoke(
        add_forecast,
        to_flags({"sensor": sensor_id, "parameters": str(parameters_file)})
        + ["--as-job"],
    )

    assert result.exit_code == 1
    assert "The --as-job flag cannot be combined with --dry-run" in result.output


def test_add_forecast_reports_invalid_annotation_regressor(app, setup_dummy_data):
    from flexmeasures.cli.data_add import add_forecast

    sensor_id, *_ = setup_dummy_data
    runner = app.test_cli_runner()
    result = runner.invoke(
        add_forecast,
        [
            "--sensor",
            str(sensor_id),
            "--annotation-regressors",
            '{"annotation-type": "label"}',
        ],
    )

    assert result.exit_code == 2
    assert "Invalid forecasting configuration" in result.output
    assert "Specify exactly one of account, asset, or sensor." in result.output
    assert "Traceback" not in result.output


def test_add_forecast_rejects_config_with_existing_source(app, db, setup_dummy_data):
    from flexmeasures.cli.data_add import add_forecast

    sensor_id, *_ = setup_dummy_data
    source = DataSource(
        name="stored forecaster",
        type="forecaster",
        model="TrainPredictPipeline",
    )
    db.session.add(source)
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(
        add_forecast,
        [
            "--source",
            str(source.id),
            "--sensor",
            str(sensor_id),
            "--annotation-regressors",
            '{"account": 1, "annotation-type": "holiday"}',
        ],
    )

    assert result.exit_code == 2
    assert "--source uses the forecaster configuration stored with that source" in (
        result.output
    )


@pytest.mark.parametrize(
    "event_resolution, name, success",
    [("PT20M", "ONE", True), (15, "TWO", True), ("some_string", "THREE", False)],
)
def test_add_sensor(app, db, setup_dummy_asset, event_resolution, name, success):
    from flexmeasures.cli.data_add import add_sensor

    asset = setup_dummy_asset

    runner = app.test_cli_runner()

    cli_input = {
        "name": name,
        "event-resolution": event_resolution,
        "unit": "kWh",
        "asset": asset,
        "timezone": "UTC",
    }
    runner = app.test_cli_runner()
    result = runner.invoke(add_sensor, to_flags(cli_input))
    sensor: Sensor = db.session.execute(
        select(Sensor).filter_by(name=name)
    ).scalar_one_or_none()
    if success:
        check_command_ran_without_error(result)
        sensor.unit == "kWh"
    else:
        assert result.exit_code == 1
        assert sensor is None


@pytest.mark.parametrize(
    "name, consultancy_account_id, success",
    [
        ("Test ConsultancyClient Account", 1, False),
        ("Test CLIConsultancyClient Account", 2, True),
        ("Test Account", None, True),
    ],
)
def test_add_account(app, db, setup_accounts, name, consultancy_account_id, success):
    """Test adding a new account."""

    from flexmeasures.cli.data_add import new_account

    cli_input = {
        "name": name,
        "roles": "TestRole",
        "consultancy": consultancy_account_id,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(new_account, to_flags(cli_input))
    if success:
        assert "successfully created." in result.output
        account = db.session.execute(
            select(Account).filter_by(name=cli_input["name"])
        ).scalar_one_or_none()
        assert account.consultancy_account_id == consultancy_account_id
        audit_log = db.session.execute(
            select(AuditLog).filter_by(affected_account_id=account.id)
        ).scalar_one()
        assert audit_log.event == f"Created organisation '{name}': {account.id} via CLI"
        assert audit_log.active_user_id is None

    else:
        # fail because "Test ConsultancyClient Account" already exists
        assert result.exit_code == 1


@pytest.mark.parametrize(
    "roles_args, expected_roles",
    [
        (["--roles", "consultant,account-admin"], {"consultant", "account-admin"}),
        (
            ["--roles", "consultant", "--roles", "account-admin"],
            {"consultant", "account-admin"},
        ),
        (
            ["--roles", "consultant,account-admin", "--roles", "admin"],
            {"consultant", "account-admin", "admin"},
        ),
        ([], set()),
    ],
)
def test_add_user_roles(
    app,
    db,
    setup_accounts,
    monkeypatch,
    request,
    roles_args,
    expected_roles,
):
    """``--roles`` accepts a comma-separated list and/or repeated options (see issue #1237)."""
    from flexmeasures.cli.data_add import new_user

    monkeypatch.setattr("getpass.getpass", lambda prompt="": "testtest")

    account = setup_accounts["Prosumer"]
    # Name the user after the parametrization, as users persist for the other tests in this module.
    username = f"cli-user-{request.node.callspec.id}"
    email = f"{username}@example.com"

    runner = app.test_cli_runner()
    result = runner.invoke(
        new_user,
        [
            "--username",
            username,
            "--email",
            email,
            "--account",
            str(account.id),
            "--timezone",
            "UTC",
            *roles_args,
        ],
    )
    check_command_ran_without_error(result)
    assert "Successfully created user" in result.output

    user = db.session.execute(select(User).filter_by(username=username)).scalar_one()
    assert {role.name for role in user.roles} == expected_roles
