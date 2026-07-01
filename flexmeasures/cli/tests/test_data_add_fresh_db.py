import pytest
import json
import yaml
import logging
import os
from datetime import datetime
import pytz
from sqlalchemy import select

from flexmeasures import Asset
from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.time_series import Sensor, TimedBelief

from flexmeasures.cli.tests.utils import check_command_ran_without_error
from flexmeasures.utils.time_utils import server_now
from flexmeasures.tests.utils import get_test_sensor


def test_add_forecast(app, setup_dummy_data):
    from flexmeasures.cli.data_add import add_forecast

    cli_input = {
        "sensor": 1,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(add_forecast, to_flags(cli_input))
    assert result.exit_code == 0, result.output


def test_add_reporter(app, fresh_db, setup_dummy_data, caplog):
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
    caplog.set_level(logging.INFO)

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
        check_command_ran_without_error(result)

        report_sensor = fresh_db.session.get(
            Sensor, report_sensor_id
        )  # get fresh report sensor instance

        assert "Reporter PandasReporter found." in caplog.text
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

    # Running the command without timing params (start-offset/end-offset nor start/end).
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
        check_command_ran_without_error(result)

        # Check if the report is saved to the database
        report_sensor = fresh_db.session.get(
            Sensor, report_sensor_id
        )  # get fresh report sensor instance

        assert (
            "Reporter `PandasReporter` fetched successfully from the database."
            in caplog.text
        )
        assert f"Report computation done for sensor `{report_sensor}`." in result.output

        stored_report = report_sensor.search_beliefs(
            event_starts_after=previous_command_end,
            event_ends_before=server_now(),
        )

        assert len(stored_report) == 95


def test_add_multiple_output(app, fresh_db, setup_dummy_data, caplog):
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
    caplog.set_level(logging.INFO)

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
        check_command_ran_without_error(result)

        assert os.path.exists("test-df_agg.csv")
        assert os.path.exists("test-df_sub.csv")

        report_sensor = fresh_db.session.get(Sensor, report_sensor_id)
        report_sensor_2 = fresh_db.session.get(Sensor, report_sensor_2_id)

        assert "Reporter PandasReporter found" in caplog.text
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


@pytest.mark.parametrize("process_type", [("INFLEXIBLE"), ("SHIFTABLE"), ("BREAKABLE")])
def test_add_process(
    app, process_power_sensor, process_type, add_market_prices_fresh_db, db
):
    """
    Schedule a 4h of consumption block at a constant power of 400kW in a day using
    the three process policies: INFLEXIBLE, SHIFTABLE and BREAKABLE.
    """

    from flexmeasures.cli.data_add import add_schedule

    epex_da = get_test_sensor(db)

    process_power_sensor_id = process_power_sensor
    flex_context = {"consumption-price": {"sensor": epex_da.id}}
    flex_model = {
        "duration": "PT4H",
        "power": "0.4",
        "process-type": process_type,
        "time-restrictions": [
            {"start": "2015-01-02T00:00:00+01:00", "duration": "PT2H"}
        ],
    }

    cli_input_params = {
        "sensor": process_power_sensor_id,
        "start": "2015-01-02T00:00:00+01:00",
        "duration": "PT24H",
        "scheduler": "ProcessScheduler",
        "flex-context": json.dumps(flex_context),
        "flex-model": json.dumps(flex_model),
    }

    cli_input = to_flags(cli_input_params)
    runner = app.test_cli_runner()

    # call command
    result = runner.invoke(add_schedule, cli_input)
    check_command_ran_without_error(result)
    # ProcessScheduler's make_schedule() call returns an empty dict (not the
    # boolean True), which used to be falsy enough to silently suppress this
    # message; confirm the message still appears.
    assert "New schedule is stored." in result.output

    process_power_sensor = db.session.get(Sensor, process_power_sensor_id)
    schedule = process_power_sensor.search_beliefs()
    # check if the schedule is not empty more detailed testing can be found
    # in data/models/planning/tests/test_process.py.
    assert (schedule == -0.4).event_value.sum() == 4


@pytest.mark.parametrize(
    "event_resolution, name, success",
    [("PT20M", "ONE", True), (15, "TWO", True), ("some_string", "THREE", False)],
)
def test_add_sensor(app, fresh_db, setup_dummy_asset, event_resolution, name, success):
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
    sensor: Sensor = fresh_db.session.execute(
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


def test_add_process_toy_account_reuses_existing_root_assets(app, fresh_db):
    from flexmeasures.cli.data_add import add_toy_account

    runner = app.test_cli_runner()
    result = runner.invoke(add_toy_account)
    assert result.exit_code == 0, result.output

    result = runner.invoke(add_toy_account, ["--kind", "process"])
    assert result.exit_code == 0, result.output

    toy_account = fresh_db.session.execute(
        select(Account).filter_by(name="Toy Account")
    ).scalar_one()
    root_buildings = (
        fresh_db.session.execute(
            select(Asset).filter_by(
                name="toy-building",
                owner=toy_account,
                parent_asset_id=None,
            )
        )
        .scalars()
        .all()
    )
    root_processes = (
        fresh_db.session.execute(
            select(Asset).filter_by(
                name="toy-process",
                owner=toy_account,
                parent_asset_id=None,
            )
        )
        .scalars()
        .all()
    )

    assert len(root_buildings) == 1
    assert len(root_processes) == 1
    assert {sensor.name for sensor in root_processes[0].sensors} == {
        "Power (Inflexible)",
        "Power (Breakable)",
        "Power (Shiftable)",
    }


@pytest.mark.parametrize("storage_power_capacity", ["sensor", "quantity", None])
@pytest.mark.parametrize("storage_efficiency", ["sensor", "quantity", None])
def test_add_storage_schedule(
    app,
    add_market_prices_fresh_db,
    storage_schedule_sensors,
    storage_power_capacity,
    storage_efficiency,
    fresh_db,
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
    4. Executes the 'add_schedule' command with the configured parameters.
    5. Verifies that the command executes successfully (exit code 0) and that the correct number of scheduled
       values (48 for a 12-hour period with 15-minute resolution) are created for the power sensor.
    """
    power_capacity_sensor, storage_efficiency_sensor = storage_schedule_sensors

    from flexmeasures.cli.data_add import add_schedule, add_toy_account

    runner = app.test_cli_runner()
    runner.invoke(add_toy_account)

    toy_account = fresh_db.session.execute(
        select(Account).filter_by(name="Toy Account")
    ).scalar_one_or_none()
    battery = fresh_db.session.execute(
        select(Asset).filter_by(name="toy-battery", owner=toy_account)
    ).scalar_one_or_none()
    power_sensor = battery.sensors[0]
    prices = add_market_prices_fresh_db["epex_da"]

    flex_context = {"consumption-price": {"sensor": prices.id}}
    flex_model = {
        "roundtrip-efficiency": "90%",
    }

    cli_input_params = {
        "start": "2014-12-31T23:00:00+00",
        "duration": "PT12H",
        "sensor": battery.sensors[0].id,
        "scheduler": "StorageScheduler",
        "soc-at-start": "50%",
        "flex-context": flex_context,
        "flex-model": flex_model,
    }

    if storage_power_capacity is not None:
        if storage_power_capacity == "sensor":
            cli_input_params["flex-model"]["consumption-capacity"] = {
                "sensor": power_capacity_sensor
            }
            cli_input_params["flex-model"]["production-capacity"] = {
                "sensor": power_capacity_sensor
            }
        else:
            cli_input_params["flex-model"]["consumption-capacity"] = "700kW"
            cli_input_params["flex-model"]["production-capacity"] = "700kW"

    if storage_efficiency is not None:
        if storage_efficiency == "sensor":
            cli_input_params["flex-model"]["storage-efficiency"] = {
                "sensor": storage_efficiency_sensor
            }
        else:
            cli_input_params["flex-model"]["storage-efficiency"] = "90%"

    # json dump flex-model and flex-context
    cli_input_params["flex-model"] = json.dumps(cli_input_params["flex-model"])
    cli_input_params["flex-context"] = json.dumps(cli_input_params["flex-context"])

    cli_input = to_flags(cli_input_params)

    result = runner.invoke(add_schedule, cli_input)

    check_command_ran_without_error(result)
    assert len(power_sensor.search_beliefs()) == 48


def test_add_storage_schedule_uses_state_of_charge_sensor_for_soc_at_start(
    app,
    fresh_db,
    add_market_prices_fresh_db,
    add_charging_station_assets_fresh_db,
    setup_sources_fresh_db,
):
    """Test that the StorageScheduler reads soc-at-start from a sensor and stores
    schedules on dedicated consumption and production output sensors with the correct
    sign convention and clipping behaviour.

    Setup:
    - Bidirectional charging station (can both charge and discharge).
    - SOC at start: 2.5 MWh (read from a sensor belief).
    - Schedule window: 2015-01-03 00:00–12:00 CET.
      On this date the market data has consumption prices of -10 EUR/MWh for hours 0–7
      (incentivises charging) and production prices of +60 EUR/MWh for hours 8–23
      (incentivises discharging), so the optimizer is guaranteed to do both.

    Sign-convention and clipping assertions (both consumption and production sensors defined):
    - Consumption sensor (consumption_is_positive=True): all stored values ≥ 0
      (charging intervals are positive; discharging intervals are clipped to 0).
    - Production sensor (consumption_is_positive=False): all stored values ≥ 0
      (discharging intervals are stored as positive; charging intervals are clipped to 0).
    - No single timestep may carry both a positive consumption and a positive production
      value (the two sensors together partition the schedule without overlap).
    - At least one charging and one discharging event must actually occur.
    """
    from flexmeasures.cli.data_add import add_schedule

    # Use the bidirectional station so both charging and discharging can occur.
    bidirectional_charging_station = add_charging_station_assets_fresh_db[
        "Test charging station (bidirectional)"
    ]
    power_sensor = next(
        s for s in bidirectional_charging_station.sensors if s.name == "power"
    )
    soc_sensor = add_charging_station_assets_fresh_db["bi-soc"]

    # 2015-01-03: consumption prices are -10 EUR/MWh in hours 0-7 (charging rewarded)
    # and production prices are +60 EUR/MWh in hours 8-23 (discharging rewarded).
    start = "2015-01-03T00:00:00+01:00"

    fresh_db.session.add(
        TimedBelief(
            sensor=soc_sensor,
            source=setup_sources_fresh_db["Seita"],
            event_start=datetime.fromisoformat(start),
            event_value=2.5,
            belief_time=datetime.fromisoformat(start),
        )
    )

    # Add dedicated output sensors for the consumption (charging) and production
    # (discharging) parts of the schedule.
    consumption_output_sensor = Sensor(
        name="consumption output",
        generic_asset=bidirectional_charging_station,
        unit="MW",
        event_resolution=power_sensor.event_resolution,
    )
    production_output_sensor = Sensor(
        name="production output",
        generic_asset=bidirectional_charging_station,
        unit="MW",
        event_resolution=power_sensor.event_resolution,
    )
    fresh_db.session.add(consumption_output_sensor)
    fresh_db.session.add(production_output_sensor)
    fresh_db.session.commit()

    epex_da = add_market_prices_fresh_db["epex_da"]
    epex_da_production = add_market_prices_fresh_db["epex_da_production"]

    cli_input_params = {
        "sensor": power_sensor.id,
        "start": start,
        "duration": "PT12H",
        "scheduler": "StorageScheduler",
        "flex-context": json.dumps(
            {
                "consumption-price": {"sensor": epex_da.id},
                "production-price": {"sensor": epex_da_production.id},
            }
        ),
        "flex-model": json.dumps(
            {
                "state-of-charge": {"sensor": soc_sensor.id},
                "soc-min": "0 MWh",
                "soc-max": "5 MWh",
                "power-capacity": "2 MW",
                "consumption": {"sensor": consumption_output_sensor.id},
                "production": {"sensor": production_output_sensor.id},
            }
        ),
    }

    result = app.test_cli_runner().invoke(add_schedule, to_flags(cli_input_params))

    check_command_ran_without_error(result)
    assert len(power_sensor.search_beliefs()) == 48
    assert power_sensor.generic_asset.get_attribute("soc_in_mwh") == 2.5

    # Reload sensors from the DB after the schedule has been committed.
    consumption_output_sensor = fresh_db.session.get(
        Sensor, consumption_output_sensor.id
    )
    production_output_sensor = fresh_db.session.get(Sensor, production_output_sensor.id)
    consumption_beliefs = consumption_output_sensor.search_beliefs()
    production_beliefs = production_output_sensor.search_beliefs()

    assert len(consumption_beliefs) == 48
    assert len(production_beliefs) == 48

    consumption_values = consumption_beliefs.values.flatten()
    production_values = production_beliefs.values.flatten()

    # Sign convention: consumption sensor (consumption_is_positive=True) stores
    # charging as positive values; discharging intervals are clipped to 0.
    assert (
        consumption_values >= 0
    ).all(), "Consumption output sensor must only hold non-negative values"
    # Sign convention: production sensor (consumption_is_positive=False) stores
    # discharging as positive values; charging intervals are clipped to 0.
    assert (
        production_values >= 0
    ).all(), "Production output sensor must only hold non-negative values"
    # Clipping: the two sensors partition the schedule without overlap — no
    # single timestep should carry both a positive consumption and a positive
    # production value.
    assert not (
        (consumption_values > 0) & (production_values > 0)
    ).any(), "No timestep may have both positive consumption and positive production"
    # With negative consumption prices in hours 0-7 and positive production prices
    # in hours 8+, both charging and discharging must occur.
    assert (
        consumption_values > 0
    ).any(), "Some charging must occur given the negative consumption prices"
    assert (
        production_values > 0
    ).any(), "Some discharging must occur given the positive production prices"
