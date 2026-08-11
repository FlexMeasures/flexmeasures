from datetime import datetime, timedelta, timezone
import json

import pytest
import pytz
from types import SimpleNamespace

from sqlalchemy import select

from flexmeasures import Sensor
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.utils.time_utils import get_timezone


@pytest.fixture(scope="function")
def clean_redis(app):
    app.redis_connection.flushdb()
    yield
    app.redis_connection.flushdb()


@pytest.fixture()
def automation_scope_assets(fresh_db, setup_dummy_data):
    root_sensor = fresh_db.session.get(Sensor, setup_dummy_data[0])
    root_asset = root_sensor.generic_asset
    asset_type = root_asset.generic_asset_type

    ancestor = GenericAsset(name="automation ancestor", generic_asset_type=asset_type)
    child = GenericAsset(
        name="automation child",
        generic_asset_type=asset_type,
        parent_asset=root_asset,
    )
    grandchild = GenericAsset(
        name="automation grandchild",
        generic_asset_type=asset_type,
        parent_asset=child,
    )
    unrelated = GenericAsset(name="automation unrelated", generic_asset_type=asset_type)
    root_asset.parent_asset = ancestor

    sensors = {"root": root_sensor}
    for name, asset in (
        ("ancestor", ancestor),
        ("child", child),
        ("grandchild", grandchild),
        ("unrelated", unrelated),
    ):
        sensors[name] = Sensor(
            f"{name} output",
            generic_asset=asset,
            event_resolution=root_sensor.event_resolution,
            unit=root_sensor.unit,
        )

    fresh_db.session.add_all(
        [ancestor, child, grandchild, unrelated, *sensors.values()]
    )
    fresh_db.session.commit()
    return {
        "root_asset": root_asset,
        "child_asset": child,
        "unrelated_asset": unrelated,
        "sensors": sensors,
    }


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
        "timezone": "Europe/Amsterdam",
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
    assert automation.timezone == "Europe/Amsterdam"
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
        [
            "--id",
            automation.id,
            "--name",
            "Renamed",
            "--timezone",
            "UTC",
            "--deactivate",
        ],
    )
    assert "Successfully updated" in result.output, result.output
    assert automation.name == "Renamed"
    assert automation.timezone == "UTC"
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


def test_add_automation_default_cron(
    app, fresh_db, setup_dummy_data, freeze_server_now
):
    """Without --cron, an automation recurs daily."""
    from flexmeasures.cli.data_add import add_automation
    from flexmeasures.data.services.automations import (
        claim_due_automation,
        get_due_automations,
    )

    # create the automation before the midnight we check, as an automation does not replay occurrences from before it existed
    midnight = get_timezone().localize(datetime(2026, 7, 11, 0, 0))
    freeze_server_now(midnight - timedelta(hours=3))

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

    # due at midnight in the automation's timezone
    due = get_due_automations(midnight)
    assert [d.automation.id for d in due] == [automation.id]

    # and, once claimed, not handed out again an hour later
    assert claim_due_automation(due[0])
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

    # a configuration option given on the command line conflicts, too
    result = runner.invoke(
        add_automation,
        to_flags(
            {
                "asset": 1,
                "name": "Second",
                "sensor": sensor_id,
                "source": source_id,
                "regressors": sensor_id,
            }
        ),
    )
    assert result.exit_code != 0
    assert "--regressors cannot be combined with --source" in result.output

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


def test_automation_sensors_with_source_filtered_regressor(
    app, fresh_db, setup_dummy_data
):
    """A regressor that filters on sources still counts as an input sensor.

    The source filters only narrow down which beliefs are read from that sensor,
    so leaving it out would understate which sensors the automation reads from.
    """
    from flexmeasures.cli.data_add import add_automation

    sensor_id, regressor_id = setup_dummy_data[0], setup_dummy_data[1]
    runner = app.test_cli_runner()
    result = runner.invoke(
        add_automation,
        to_flags(
            {
                "asset": 1,
                "name": "Filtered regressor forecasts",
                "sensor": sensor_id,
                "regressors": json.dumps(
                    [{"sensor": regressor_id, "source-types": ["forecaster"]}]
                ),
            }
        ),
    )
    assert "Successfully created" in result.output, result.output
    automation = fresh_db.session.execute(
        select(Automation).filter_by(name="Filtered regressor forecasts")
    ).scalar_one()
    assert sorted(sensor.id for sensor in automation.input_sensors) == sorted(
        [sensor_id, regressor_id]
    )


def test_automation_sensors_are_unknown_rather_than_empty(
    app, fresh_db, setup_dummy_data
):
    """When the sensors cannot be worked out, only the display helper is allowed to report none.

    Reporting no sensors to an access check would let the automation pass every check on the sensors it involves,
    so the strict helper raises instead.
    """
    from flexmeasures.cli.data_add import add_automation
    from flexmeasures.data.services.automations import (
        AutomationSensorsUnknown,
        get_automation_sensors,
        resolve_automation_sensors,
    )

    sensor_id = setup_dummy_data[0]
    runner = app.test_cli_runner()
    result = runner.invoke(
        add_automation,
        to_flags({"asset": 1, "name": "Broken forecasts", "sensor": sensor_id}),
    )
    assert "Successfully created" in result.output, result.output
    automation = fresh_db.session.execute(
        select(Automation).filter_by(name="Broken forecasts")
    ).scalar_one()

    # the parameters no longer load, as happens when a sensor referred to has been deleted
    automation.parameters = {"sensor": "no-such-sensor"}
    fresh_db.session.commit()

    assert get_automation_sensors(automation) == {
        "input_sensors": [],
        "output_sensors": [],
    }
    with pytest.raises(AutomationSensorsUnknown):
        resolve_automation_sensors(automation)


@pytest.mark.parametrize("cronstr", ["not a cron string", "0 0 31 2 *"])
def test_add_automation_invalid_cron(app, fresh_db, setup_dummy_data, cronstr):
    from flexmeasures.cli.data_add import add_automation

    sensor_id = setup_dummy_data[0]
    runner = app.test_cli_runner()
    cli_input = {
        "asset": 1,
        "name": "Test forecasts",
        "cron": cronstr,
        "sensor": sensor_id,
    }
    result = runner.invoke(add_automation, to_flags(cli_input))
    assert result.exit_code != 0
    # NB click reports the offending value; once it reports the validation message
    # instead (see PR #2303), the cron string's own error text shows up here.
    assert "Invalid value" in result.output


def test_add_automation_defaults_to_configured_timezone(
    app, fresh_db, setup_dummy_data, monkeypatch
):
    from flexmeasures.cli.data_add import add_automation

    monkeypatch.setitem(app.config, "FLEXMEASURES_TIMEZONE", "America/New_York")
    result = app.test_cli_runner().invoke(
        add_automation,
        [
            "--asset",
            "1",
            "--name",
            "Configured timezone",
            "--cron",
            "0 6 * * *",
            "--sensor",
            str(setup_dummy_data[0]),
        ],
    )

    assert result.exit_code == 0, result.output
    automation = fresh_db.session.scalars(select(Automation)).one()
    assert automation.timezone == "America/New_York"


def test_add_and_edit_automation_reject_invalid_timezone(
    app, fresh_db, setup_dummy_data
):
    from flexmeasures.cli.data_add import add_automation
    from flexmeasures.cli.data_edit import edit_automation

    runner = app.test_cli_runner()
    invalid_add = runner.invoke(
        add_automation,
        [
            "--asset",
            "1",
            "--name",
            "Invalid timezone",
            "--cron",
            "0 6 * * *",
            "--timezone",
            "Europe/NotAmsterdam",
            "--sensor",
            str(setup_dummy_data[0]),
        ],
    )
    assert invalid_add.exit_code != 0
    assert fresh_db.session.scalars(select(Automation)).all() == []

    valid_add = runner.invoke(
        add_automation,
        [
            "--asset",
            "1",
            "--name",
            "Valid timezone",
            "--cron",
            "0 6 * * *",
            "--timezone",
            "UTC",
            "--sensor",
            str(setup_dummy_data[0]),
        ],
    )
    assert valid_add.exit_code == 0, valid_add.output
    automation = fresh_db.session.scalars(select(Automation)).one()
    invalid_edit = runner.invoke(
        edit_automation,
        ["--id", str(automation.id), "--timezone", "Europe/NotAmsterdam"],
    )
    assert invalid_edit.exit_code != 0
    assert automation.timezone == "UTC"


@pytest.mark.parametrize(
    "edit_args",
    (
        ["--cron", "15 10 * * *"],
        ["--timezone", "Europe/Amsterdam"],
        ["--activate"],
    ),
)
def test_edit_automation_rebases_scheduling_cursor(
    app,
    fresh_db,
    setup_dummy_data,
    freeze_server_now,
    edit_args,
):
    from flexmeasures.cli.data_add import add_automation
    from flexmeasures.cli.data_edit import edit_automation

    freeze_server_now(datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc))
    runner = app.test_cli_runner()
    add_result = runner.invoke(
        add_automation,
        [
            "--asset",
            "1",
            "--name",
            "Rebased automation",
            "--cron",
            "0 10 * * *",
            "--timezone",
            "UTC",
            "--inactive",
            "--sensor",
            str(setup_dummy_data[0]),
        ],
    )
    assert add_result.exit_code == 0, add_result.output
    automation = fresh_db.session.scalars(select(Automation)).one()

    freeze_server_now(datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc))
    edit_result = runner.invoke(
        edit_automation, ["--id", str(automation.id), *edit_args]
    )

    assert edit_result.exit_code == 0, edit_result.output
    assert automation.scheduling_cursor == datetime(
        2026, 1, 15, 9, 59, tzinfo=timezone.utc
    )


def test_add_automation_help_focuses_on_automation_options(app):
    """The forecast schema options are accepted, but kept out of the help text."""
    from flexmeasures.cli.data_add import add_automation

    result = app.test_cli_runner().invoke(add_automation, ["--help"])

    assert result.exit_code == 0, result.output
    for automation_option in (
        "--asset",
        "--name",
        "--cron",
        "--timezone",
        "--config",
        "--parameters",
    ):
        assert automation_option in result.output
    for forecast_option in ("--sensor ", "--duration", "--train-start"):
        assert forecast_option not in result.output


def test_add_automation_accepts_required_sensor_from_parameters_file(
    app, fresh_db, setup_dummy_data, tmp_path
):
    """The schema requires a sensor, but it may come from --parameters rather than the command line."""
    from flexmeasures.cli.data_add import add_automation

    parameters_file = tmp_path / "parameters.yml"
    parameters_file.write_text(f"sensor: {setup_dummy_data[0]}\n")

    result = app.test_cli_runner().invoke(
        add_automation,
        to_flags(
            {
                "asset": 1,
                "name": "YAML sensor",
                "parameters": str(parameters_file),
            }
        ),
    )

    assert "Successfully created" in result.output, result.output
    automation = fresh_db.session.execute(
        select(Automation).filter_by(name="YAML sensor")
    ).scalar_one()
    assert automation.parameters == {"sensor": setup_dummy_data[0]}


@pytest.mark.parametrize(
    ("output_sensor_name", "should_succeed"),
    (
        ("root", True),
        ("child", True),
        ("grandchild", True),
        ("unrelated", False),
        ("ancestor", False),
    ),
)
def test_add_automation_constrains_output_to_asset_subtree(
    app,
    fresh_db,
    automation_scope_assets,
    output_sensor_name,
    should_succeed,
):
    from flexmeasures.cli.data_add import add_automation

    root_asset = automation_scope_assets["root_asset"]
    output_sensor = automation_scope_assets["sensors"][output_sensor_name]

    result = app.test_cli_runner().invoke(
        add_automation,
        [
            "--asset",
            str(root_asset.id),
            "--name",
            f"{output_sensor_name} output",
            "--cron",
            "0 6 * * *",
            "--sensor",
            str(output_sensor.id),
        ],
    )

    automations = fresh_db.session.scalars(select(Automation)).all()
    if should_succeed:
        assert result.exit_code == 0, result.output
        assert len(automations) == 1
    else:
        assert result.exit_code != 0
        assert "must belong to asset" in result.output
        assert automations == []


def test_add_automation_constrains_explicit_output_sensor(
    app, fresh_db, automation_scope_assets
):
    from flexmeasures.cli.data_add import add_automation

    root_asset = automation_scope_assets["root_asset"]
    root_sensor = automation_scope_assets["sensors"]["root"]
    unrelated_sensor = automation_scope_assets["sensors"]["unrelated"]

    result = app.test_cli_runner().invoke(
        add_automation,
        [
            "--asset",
            str(root_asset.id),
            "--name",
            "unrelated explicit output",
            "--cron",
            "0 6 * * *",
            "--sensor",
            str(root_sensor.id),
            "--sensor-to-save",
            str(unrelated_sensor.id),
        ],
    )

    assert result.exit_code != 0
    assert "must belong to asset" in result.output
    assert fresh_db.session.scalars(select(Automation)).all() == []


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


@pytest.mark.parametrize("option_name", ("--config", "--parameters"))
def test_add_automation_rejects_malformed_yaml_file(
    app, fresh_db, setup_dummy_data, tmp_path, option_name
):
    from flexmeasures.cli.data_add import add_automation

    malformed_file = tmp_path / "malformed.yaml"
    malformed_file.write_text("field: [\n")
    result = app.test_cli_runner().invoke(
        add_automation,
        [
            "--asset",
            "1",
            "--name",
            "Malformed YAML",
            "--cron",
            "0 6 * * *",
            option_name,
            str(malformed_file),
            "--sensor",
            str(setup_dummy_data[0]),
        ],
    )

    assert result.exit_code == 2, result.output
    assert f"The {option_name} file is not valid YAML or JSON" in result.output
    assert "Traceback" not in result.output


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


@pytest.mark.parametrize(
    "parameters_yaml",
    (
        'resolution: "P1M"\n',
        'resolution: "PT0S"\n',
        'resolution: "-PT15M"\n',
        'duration: "PT0S"\n',
        'duration: "-PT1H"\n',
    ),
)
def test_add_schedule_automation_rejects_unsupported_durations(
    app, fresh_db, setup_dummy_data, tmp_path, parameters_yaml
):
    from flexmeasures.cli.data_add import add_automation

    parameters_file = tmp_path / "parameters.yml"
    parameters_file.write_text(parameters_yaml)
    result = app.test_cli_runner().invoke(
        add_automation,
        [
            "--asset",
            "1",
            "--name",
            "Invalid schedule durations",
            "--cron",
            "0 * * * *",
            "--type",
            "schedules",
            "--parameters",
            str(parameters_file),
        ],
    )

    assert result.exit_code != 0
    assert "Invalid schedule parameters" in result.output


def test_add_schedule_automation_rejects_forecast_config(
    app, fresh_db, setup_dummy_data
):
    from flexmeasures.cli.data_add import add_automation

    result = app.test_cli_runner().invoke(
        add_automation,
        [
            "--asset",
            "1",
            "--name",
            "Schedule with ignored forecast config",
            "--cron",
            "0 * * * *",
            "--type",
            "schedules",
            "--regressors",
            str(setup_dummy_data[0]),
        ],
    )

    assert result.exit_code == 2
    assert "Forecaster options" in result.output
    assert "Traceback" not in result.output


def test_add_forecast_automation_still_requires_sensor(app, fresh_db, setup_dummy_data):
    from flexmeasures.cli.data_add import add_automation

    result = app.test_cli_runner().invoke(
        add_automation,
        ["--asset", "1", "--name", "No sensor", "--cron", "0 * * * *"],
    )

    assert result.exit_code != 0
    assert "Invalid forecast parameters" in result.output


@pytest.mark.parametrize("is_dst", (True, False))
def test_prepare_schedule_start_floors_both_dst_folds(app, monkeypatch, is_dst):
    from flexmeasures.data.services import automations

    timezone = pytz.timezone("Europe/Amsterdam")
    now = timezone.localize(datetime(2026, 10, 25, 2, 7, 30), is_dst=is_dst)
    monkeypatch.setattr(automations, "server_now", lambda: now)
    parameters = {"duration": "PT1H", "resolution": "PT15M"}

    message = automations.prepare_schedule_trigger_message(parameters, asset_id=1)

    assert datetime.fromisoformat(message["start"]) == now.replace(
        minute=0, second=0, microsecond=0
    )
    assert parameters == {"duration": "PT1H", "resolution": "PT15M"}


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
    assert "No automations due" in result.output, result.output
    assert len(app.queues["forecasting"].jobs) == n_jobs

    # inactive automations are not due
    for automation in automations:
        automation.active = False
    fresh_db.session.commit()
    app.redis_connection.flushdb()
    result = runner.invoke(run_automations)
    assert "No automations due" in result.output, result.output


def test_run_automations_catches_up_once_after_downtime(
    app,
    fresh_db,
    setup_dummy_data,
    clean_redis,
    freeze_server_now,
):
    from flexmeasures.cli.data_add import add_automation
    from flexmeasures.cli.jobs import run_automations

    freeze_server_now(datetime(2026, 1, 15, 8, 58, 30, tzinfo=timezone.utc))
    runner = app.test_cli_runner()
    add_result = runner.invoke(
        add_automation,
        [
            "--asset",
            "1",
            "--name",
            "Amsterdam catch-up",
            "--cron",
            "0 10 * * *",
            "--timezone",
            "Europe/Amsterdam",
            "--sensor",
            str(setup_dummy_data[0]),
        ],
    )
    assert add_result.exit_code == 0, add_result.output

    freeze_server_now(datetime(2026, 1, 15, 9, 5, tzinfo=timezone.utc))
    first_result = runner.invoke(run_automations)
    assert first_result.exit_code == 0, first_result.output
    assert first_result.output.count("queued") == 1
    n_jobs = app.queues["forecasting"].count
    assert n_jobs > 0

    fresh_db.session.remove()
    second_result = runner.invoke(run_automations)
    assert second_result.exit_code == 0, second_result.output
    assert "No automations due" in second_result.output
    assert app.queues["forecasting"].count == n_jobs

    automation = fresh_db.session.scalars(select(Automation)).one()
    assert automation.timezone == "Europe/Amsterdam"
    assert automation.scheduling_cursor == datetime(
        2026, 1, 15, 9, 0, tzinfo=timezone.utc
    )


def test_failed_automation_attempt_is_not_retried(app, clean_redis, mocker):
    """A failure after partial queueing must not duplicate that work on retry."""
    from flexmeasures.cli.jobs import run_automations
    from flexmeasures.data.services.automations import DueAutomation

    automation = SimpleNamespace(id=42, name="Partial run", asset_id=1)
    due_automation = DueAutomation(
        automation=automation,
        scheduled_at=datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc),
        expected_cursor=datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc),
        expected_cronstr="0 * * * *",
        expected_timezone="UTC",
    )
    mocker.patch(
        "flexmeasures.cli.jobs.get_due_automations", return_value=[due_automation]
    )
    mocker.patch("flexmeasures.cli.jobs.claim_due_automation", return_value=True)

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


def test_run_automation_revalidates_output_scope(
    app, fresh_db, automation_scope_assets, clean_redis
):
    from flexmeasures.cli.data_add import add_automation
    from flexmeasures.cli.jobs import run_automations

    root_asset = automation_scope_assets["root_asset"]
    child_asset = automation_scope_assets["child_asset"]
    unrelated_asset = automation_scope_assets["unrelated_asset"]
    child_sensor = automation_scope_assets["sensors"]["child"]
    runner = app.test_cli_runner()

    add_result = runner.invoke(
        add_automation,
        [
            "--asset",
            str(root_asset.id),
            "--name",
            "moved output",
            "--cron",
            "* * * * *",
            "--sensor",
            str(child_sensor.id),
        ],
    )
    assert add_result.exit_code == 0, add_result.output

    child_asset.parent_asset = unrelated_asset
    fresh_db.session.commit()
    fresh_db.session.expire_all()

    run_result = runner.invoke(run_automations)

    assert run_result.exit_code == 1
    assert "must belong to asset" in run_result.output
    assert app.queues["forecasting"].count == 0
