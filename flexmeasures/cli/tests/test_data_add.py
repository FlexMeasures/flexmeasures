import pytest
import json
import yaml
import os
from datetime import datetime
import pytz
from sqlalchemy import select, func

from flexmeasures import Asset
from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.annotations import (
    Annotation,
    AccountAnnotationRelationship,
)
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor

from flexmeasures.cli.tests.utils import get_click_commands
from flexmeasures.utils.time_utils import server_now
from flexmeasures.tests.utils import get_test_sensor


@pytest.mark.skip_github
def test_add_annotation(app, db, setup_roles_users):
    from flexmeasures.cli.data_add import add_annotation

    cli_input = {
        "content": "Company founding day",
        "at": "2016-05-11T00:00+02:00",
        "account": 1,
        "user": 1,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(add_annotation, to_flags(cli_input))

    # Check result for success
    assert "Successfully added annotation" in result.output

    # Check database for annotation entry
    assert db.session.execute(
        select(Annotation)
        .filter_by(
            content=cli_input["content"],
            start=cli_input["at"],
        )
        .join(AccountAnnotationRelationship)
        .filter_by(
            account_id=cli_input["account"],
            annotation_id=Annotation.id,
        )
        .join(DataSource)
        .filter_by(
            id=Annotation.source_id,
            user_id=cli_input["user"],
        )
    ).scalar_one_or_none()


@pytest.mark.skip_github
def test_add_holidays(app, db, setup_roles_users):
    from flexmeasures.cli.data_add import add_holidays

    cli_input = {
        "year": 2020,
        "country": "NL",
        "account": 1,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(add_holidays, to_flags(cli_input))

    # Check result for 11 public holidays
    assert "'NL': 11" in result.output

    # Check database for 11 annotation entries
    assert (
        db.session.scalar(
            select(func.count())
            .select_from(Annotation)
            .join(AccountAnnotationRelationship)
            .filter(
                AccountAnnotationRelationship.account_id == cli_input["account"],
                AccountAnnotationRelationship.annotation_id == Annotation.id,
            )
            .join(DataSource)
            .filter(
                DataSource.id == Annotation.source_id,
                DataSource.name == "workalendar",
                DataSource.model == cli_input["country"],
            )
        )
        == 11
    )


def test_cli_help(app):
    """Test that showing help does not throw an error."""
    from flexmeasures.cli import data_add

    runner = app.test_cli_runner()
    for cmd in get_click_commands(data_add):
        result = runner.invoke(cmd, ["--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output


@pytest.mark.skip_github
def test_add_reporter(app, fresh_db, setup_dummy_data):
    """
    The reporter aggregates input data from two sensors (both have 200 data points)
    to a two-hour resolution.

    The command is run twice:
        - The first run is for ten hours, so you expect five results.
            - start and end are defined in the configuration: 2023-04-10T00:00 -> 2023-04-10T10:00
            - this step uses 10 hours of data -> outputs 5 periods of 2 hours
        - The second is run without timing params, so the rest of the data
            - start is the time of the latest report value
            - end is the time of latest input data value
            - this step uses 190 hours of data -> outputs 95 periods of 2 hours
    """

    from flexmeasures.cli.data_add import add_report

    sensor1_id, sensor2_id, report_sensor_id, _ = setup_dummy_data

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

    # Running the command with start and end values.

    runner = app.test_cli_runner()

    cli_input_params = {
        "config": "reporter_config.yaml",
        "parameters": "parameters.json",
        "reporter": "PandasReporter",
        "start": "2023-04-10T00:00:00 00:00",
        "end": "2023-04-10T10:00:00 00:00",
        "output-file": "test.csv",
    }

    parameters = dict(
        input=[
            dict(name="sensor_1", sensor=sensor1_id),
            dict(name="sensor_2", sensor=sensor2_id),
        ],
        output=[dict(name="df_agg", sensor=report_sensor_id)],
    )

    cli_input = to_flags(cli_input_params)

    # store config into config
    cli_input.append("--save-config")

    # run test in an isolated file system
    with runner.isolated_filesystem():

        # save reporter_config to a json file
        with open("reporter_config.yaml", "w") as f:
            yaml.dump(reporter_config, f)

        with open("parameters.json", "w") as f:
            json.dump(parameters, f)

        # call command
        result = runner.invoke(add_report, cli_input)

        print(result)

        assert result.exit_code == 0  # run command without errors

        report_sensor = fresh_db.session.get(
            Sensor, report_sensor_id
        )  # get fresh report sensor instance

        assert "Reporter PandasReporter found" in result.output
        assert f"Report computation done for sensor `{report_sensor}`." in result.output

        # Check report is saved to the database
        stored_report = report_sensor.search_beliefs(
            event_starts_after=cli_input_params.get("start").replace(" ", "+"),
            event_ends_before=cli_input_params.get("end").replace(" ", "+"),
        )

        assert (
            stored_report.values.T == [1, 2 + 3, 4 + 5, 6 + 7, 8 + 9]
        ).all()  # check values

        assert os.path.exists("test.csv")  # check that the file has been created
        assert (
            os.path.getsize("test.csv") > 100
        )  # bytes. Check that the file is not empty

    # Running the command without without timing params (start-offset/end-offset nor start/end).
    # This makes the command default the start time to the date of the last
    # value of the reporter sensor and the end time as the current time.

    previous_command_end = cli_input_params.get("end").replace(" ", "+")

    cli_input_params = {
        "source": stored_report.sources[0].id,
        "parameters": "parameters.json",
        "output-file": "test.csv",
        "timezone": "UTC",
    }

    cli_input = to_flags(cli_input_params)

    with runner.isolated_filesystem():

        # save reporter_config to a json file
        with open("reporter_config.json", "w") as f:
            json.dump(reporter_config, f)

        with open("parameters.json", "w") as f:
            json.dump(parameters, f)

        # call command
        result = runner.invoke(add_report, cli_input)

        print(result)

        assert result.exit_code == 0  # run command without errors

        # Check if the report is saved to the database
        report_sensor = fresh_db.session.get(
            Sensor, report_sensor_id
        )  # get fresh report sensor instance

        assert (
            "Reporter `PandasReporter` fetched successfully from the database."
            in result.output
        )
        assert f"Report computation done for sensor `{report_sensor}`." in result.output

        stored_report = report_sensor.search_beliefs(
            event_starts_after=previous_command_end,
            event_ends_before=server_now(),
        )

        assert len(stored_report) == 95


@pytest.mark.skip_github
def test_add_multiple_output(app, fresh_db, setup_dummy_data):
    """ """

    from flexmeasures.cli.data_add import add_report

    sensor_1_id, sensor_2_id, report_sensor_id, report_sensor_2_id = setup_dummy_data

    reporter_config = dict(
        required_input=[{"name": "sensor_1"}, {"name": "sensor_2"}],
        required_output=[{"name": "df_agg"}, {"name": "df_sub"}],
        transformations=[
            dict(
                df_input="sensor_1",
                method="add",
                args=["@sensor_2"],
                df_output="df_agg",
            ),
            dict(method="resample_events", args=["2h"]),
            dict(
                df_input="sensor_1",
                method="subtract",
                args=["@sensor_2"],
                df_output="df_sub",
            ),
            dict(method="resample_events", args=["2h"]),
        ],
    )

    # Running the command with start and end values.

    runner = app.test_cli_runner()

    cli_input_params = {
        "config": "reporter_config.yaml",
        "parameters": "parameters.json",
        "reporter": "PandasReporter",
        "start": "2023-04-10T00:00:00+00:00",
        "end": "2023-04-10T10:00:00+00:00",
        "output-file": "test-$name.csv",
    }

    parameters = dict(
        input=[
            dict(name="sensor_1", sensor=sensor_1_id),
            dict(name="sensor_2", sensor=sensor_2_id),
        ],
        output=[
            dict(name="df_agg", sensor=report_sensor_id),
            dict(name="df_sub", sensor=report_sensor_2_id),
        ],
    )

    cli_input = to_flags(cli_input_params)

    # run test in an isolated file system
    with runner.isolated_filesystem():

        # save reporter_config to a json file
        with open("reporter_config.yaml", "w") as f:
            yaml.dump(reporter_config, f)

        with open("parameters.json", "w") as f:
            json.dump(parameters, f)

        # call command
        result = runner.invoke(add_report, cli_input)

        assert os.path.exists("test-df_agg.csv")
        assert os.path.exists("test-df_sub.csv")

        print(result)

        assert result.exit_code == 0  # run command without errors

        report_sensor = fresh_db.session.get(Sensor, report_sensor_id)
        report_sensor_2 = fresh_db.session.get(Sensor, report_sensor_2_id)

        assert "Reporter PandasReporter found" in result.output
        assert f"Report computation done for sensor `{report_sensor}`." in result.output
        assert (
            f"Report computation done for sensor `{report_sensor_2}`." in result.output
        )

        # check that the reports are saved
        assert all(
            report_sensor.search_beliefs(
                event_ends_before=datetime(2023, 4, 10, 10, tzinfo=pytz.UTC)
            ).values.flatten()
            == [1, 5, 9, 13, 17]
        )
        assert all(report_sensor_2.search_beliefs() == 0)


@pytest.mark.skip_github
@pytest.mark.parametrize("process_type", [("INFLEXIBLE"), ("SHIFTABLE"), ("BREAKABLE")])
def test_add_process(
    app, process_power_sensor, process_type, add_market_prices_fresh_db, db
):
    """
    Schedule a 4h of consumption block at a constant power of 400kW in a day using
    the three process policies: INFLEXIBLE, SHIFTABLE and BREAKABLE.
    """

    from flexmeasures.cli.data_add import add_schedule_process

    epex_da = get_test_sensor(db)

    process_power_sensor_id = process_power_sensor

    cli_input_params = {
        "sensor": process_power_sensor_id,
        "start": "2015-01-02T00:00:00+01:00",
        "duration": "PT24H",
        "process-duration": "PT4H",
        "process-power": "0.4MW",
        "process-type": process_type,
        "consumption-price-sensor": epex_da.id,
        "forbid": '{"start" : "2015-01-02T00:00:00+01:00", "duration" : "PT2H"}',
    }

    cli_input = to_flags(cli_input_params)
    runner = app.test_cli_runner()

    # call command
    result = runner.invoke(add_schedule_process, cli_input)

    print(result)

    assert result.exit_code == 0  # run command without errors

    process_power_sensor = db.session.get(Sensor, process_power_sensor_id)
    schedule = process_power_sensor.search_beliefs()
    # check if the schedule is not empty more detailed testing can be found
    # in data/models/planning/tests/test_processs.py.
    assert (schedule == -0.4).event_value.sum() == 4


@pytest.mark.skip_github
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
        assert result.exit_code == 0
        sensor.unit == "kWh"
    else:
        assert result.exit_code == 1
        assert sensor is None


@pytest.mark.skip_github
@pytest.mark.parametrize(
    "name, consultancy_account_id, success",
    [
        ("Test ConsultancyClient Account", 1, False),
        ("Test CLIConsultancyClient Account", 2, True),
        ("Test Account", None, True),
    ],
)
def test_add_account(
    app, fresh_db, setup_accounts_fresh_db, name, consultancy_account_id, success
):
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
        account = fresh_db.session.execute(
            select(Account).filter_by(name=cli_input["name"])
        ).scalar_one_or_none()
        assert account.consultancy_account_id == consultancy_account_id

    else:
        # fail because "Test ConsultancyClient Account" already exists
        assert result.exit_code == 1


@pytest.mark.skip_github
@pytest.mark.parametrize("storage_power_capacity", ["sensor", "quantity", None])
@pytest.mark.parametrize("storage_efficiency", ["sensor", "quantity", None])
def test_add_storage_schedule(
    app,
    add_market_prices_fresh_db,
    storage_schedule_sensors,
    storage_power_capacity,
    storage_efficiency,
    db,
):
    """
    Test the 'flexmeasures add schedule for-storage' CLI command for adding storage schedules.

    This test evaluates the command's functionality in creating storage schedules for different configurations
    of power capacity and storage efficiency. It uses a combination of sensor-based and manually specified values
    for these parameters.

    The test performs the following steps:
    1. Simulates running the `flexmeasures add toy-account` command to set up a test account.
    2. Configures CLI input parameters for scheduling, including the start time, duration, and sensor IDs.
       The test also sets up parameters for state of charge at start and roundtrip efficiency.
    3. Depending on the test parameters, adjusts power capacity and efficiency settings. These settings can be
       either sensor-based (retrieved from storage_schedule_sensors fixture), manually specified quantities,
       or left undefined.
    4. Executes the 'add_schedule_for_storage' command with the configured parameters.
    5. Verifies that the command executes successfully (exit code 0) and that the correct number of scheduled
       values (48 for a 12-hour period with 15-minute resolution) are created for the power sensor.
    """
    power_capacity_sensor, storage_efficiency_sensor = storage_schedule_sensors

    from flexmeasures.cli.data_add import add_schedule_for_storage, add_toy_account

    runner = app.test_cli_runner()
    runner.invoke(add_toy_account)

    toy_account = db.session.execute(
        select(Account).filter_by(name="Toy Account")
    ).scalar_one_or_none()
    battery = db.session.execute(
        select(Asset).filter_by(name="toy-battery", owner=toy_account)
    ).scalar_one_or_none()
    power_sensor = battery.sensors[0]
    prices = add_market_prices_fresh_db["epex_da"]

    cli_input_params = {
        "start": "2014-12-31T23:00:00+00",
        "duration": "PT12H",
        "sensor": battery.sensors[0].id,
        "consumption-price-sensor": prices.id,
        "soc-at-start": "50%",
        "roundtrip-efficiency": "90%",
    }

    if storage_power_capacity is not None:
        if storage_power_capacity == "sensor":
            cli_input_params[
                "storage-consumption-capacity"
            ] = f"sensor:{power_capacity_sensor}"
            cli_input_params[
                "storage-production-capacity"
            ] = f"sensor:{power_capacity_sensor}"
        else:

            cli_input_params["storage-consumption-capacity"] = "700kW"
            cli_input_params["storage-production-capacity"] = "700kW"

    if storage_efficiency is not None:
        if storage_efficiency == "sensor":
            cli_input_params[
                "storage-efficiency"
            ] = f"sensor:{storage_efficiency_sensor}"
        else:

            cli_input_params["storage-efficiency"] = "90%"

    cli_input = to_flags(cli_input_params)

    result = runner.invoke(add_schedule_for_storage, cli_input)

    assert result.exit_code == 0
    assert len(power_sensor.search_beliefs()) == 48
