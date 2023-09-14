import pytest
import json
import yaml
import os
from datetime import datetime
import pytz

from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.annotations import (
    Annotation,
    AccountAnnotationRelationship,
)
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor

from flexmeasures.cli.tests.utils import get_click_commands
from flexmeasures.utils.time_utils import server_now


@pytest.mark.skip_github
def test_add_annotation(app, db, setup_roles_users):
    from flexmeasures.cli.data_add import add_annotation

    cli_input = {
        "content": "Company founding day",
        "at": "2016-05-11T00:00+02:00",
        "account-id": 1,
        "user-id": 1,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(add_annotation, to_flags(cli_input))

    # Check result for success
    assert "Successfully added annotation" in result.output

    # Check database for annotation entry
    assert (
        Annotation.query.filter(
            Annotation.content == cli_input["content"],
            Annotation.start == cli_input["at"],
        )
        .join(AccountAnnotationRelationship)
        .filter(
            AccountAnnotationRelationship.account_id == cli_input["account-id"],
            AccountAnnotationRelationship.annotation_id == Annotation.id,
        )
        .join(DataSource)
        .filter(
            DataSource.id == Annotation.source_id,
            DataSource.user_id == cli_input["user-id"],
        )
        .one_or_none()
    )


@pytest.mark.skip_github
def test_add_holidays(app, db, setup_roles_users):
    from flexmeasures.cli.data_add import add_holidays

    cli_input = {
        "year": 2020,
        "country": "NL",
        "account-id": 1,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(add_holidays, to_flags(cli_input))

    # Check result for 11 public holidays
    assert "'NL': 11" in result.output

    # Check database for 11 annotation entries
    assert (
        Annotation.query.join(AccountAnnotationRelationship)
        .filter(
            AccountAnnotationRelationship.account_id == cli_input["account-id"],
            AccountAnnotationRelationship.annotation_id == Annotation.id,
        )
        .join(DataSource)
        .filter(
            DataSource.id == Annotation.source_id,
            DataSource.name == "workalendar",
            DataSource.model == cli_input["country"],
        )
        .count()
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

        report_sensor = Sensor.query.get(
            report_sensor_id
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
        report_sensor = Sensor.query.get(
            report_sensor_id
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

        report_sensor = Sensor.query.get(report_sensor_id)
        report_sensor_2 = Sensor.query.get(report_sensor_2_id)

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
    app, process_power_sensor, process_type, add_market_prices_fresh_db
):
    """
    Schedule a 4h of consumption block at a constant power of 400kW in a day using
    the three process policies: INFLEXIBLE, SHIFTABLE and BREAKABLE.
    """

    from flexmeasures.cli.data_add import add_schedule_process

    epex_da = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()

    process_power_sensor_id = process_power_sensor

    cli_input_params = {
        "sensor-id": process_power_sensor_id,
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

    process_power_sensor = Sensor.query.get(process_power_sensor_id)

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
        "asset-id": asset,
        "timezone": "UTC",
    }
    runner = app.test_cli_runner()
    result = runner.invoke(add_sensor, to_flags(cli_input))
    sensor: Sensor = Sensor.query.filter_by(name=name).one_or_none()
    if success:
        assert result.exit_code == 0
        sensor.unit == "kWh"
    else:
        assert result.exit_code == 1
        assert sensor is None
