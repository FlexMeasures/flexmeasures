import os
import warnings
from datetime import timedelta

import pytest
from sqlalchemy import select

from flexmeasures.cli.tests.utils import (
    check_command_ran_without_error,
    get_click_commands,
)
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.tests.utils import get_test_sensor

# Tests here share one database, so the rows each test adds are deleted afterwards.
pytestmark = pytest.mark.usefixtures("undo_new_rows")


def test_list_accounts(app, setup_accounts):
    from flexmeasures.cli.data_show import list_accounts

    runner = app.test_cli_runner()
    result = runner.invoke(list_accounts)

    assert "All accounts on this" in result.output
    for account in setup_accounts.values():
        assert account.name in result.output
    check_command_ran_without_error(result)


def test_list_roles(app, setup_roles_users):
    from flexmeasures.cli.data_show import list_roles

    runner = app.test_cli_runner()
    result = runner.invoke(list_roles)

    assert "Account roles" in result.output
    assert "User roles" in result.output
    for role in ("account-admin", "Supplier", "Dummy"):
        assert role in result.output
    check_command_ran_without_error(result)


def test_list_asset_types(app, setup_generic_asset_types):
    from flexmeasures.cli.data_show import list_asset_types

    runner = app.test_cli_runner()
    result = runner.invoke(list_asset_types)

    for asset_type in setup_generic_asset_types.values():
        assert asset_type.name in result.output
    check_command_ran_without_error(result)


def test_list_sources(app, setup_sources):
    from flexmeasures.cli.data_show import list_data_sources

    runner = app.test_cli_runner()
    result = runner.invoke(list_data_sources)

    for source in setup_sources.values():
        assert source.name in result.output
    check_command_ran_without_error(result)


def test_list_sources_shows_account(app, db, setup_accounts):
    """The account a source belongs to is what tells apart otherwise identical sources."""
    from flexmeasures.cli.data_show import list_data_sources
    from flexmeasures.data.models.data_sources import DataSource

    account = setup_accounts["Prosumer"]
    db.session.add(DataSource(name="Ada", type="demo script", account_id=account.id))
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(list_data_sources)

    check_command_ran_without_error(result)
    assert "Account ID" in result.output
    assert str(account.id) in result.output


def test_list_source_sensors(app, db, setup_dummy_data):
    """A source which recorded beliefs on two sensors lists both, with their asset."""
    from flexmeasures.cli.data_show import list_data_sources
    from flexmeasures.data.models.data_sources import DataSource

    source = db.session.execute(
        select(DataSource).filter_by(name="source1")
    ).scalar_one()

    runner = app.test_cli_runner()
    result = runner.invoke(
        list_data_sources, ["--id", str(source.id), "--show-sensors"]
    )

    check_command_ran_without_error(result)
    assert f"Sensors with data from data source {source.id}" in result.output
    for sensor_name in ("sensor 1", "sensor 2"):
        assert sensor_name in result.output
    # The sensors' asset is shown, and sensors without data from this source are not listed
    assert "DummyGenericAsset" in result.output
    assert "report sensor" not in result.output


def test_list_source_sensors_without_any_data(app, setup_sources):
    """A source which recorded no beliefs at all says so, rather than showing an empty table."""
    from flexmeasures.cli.data_show import list_data_sources

    source = setup_sources["Seita"]

    runner = app.test_cli_runner()
    result = runner.invoke(
        list_data_sources, ["--id", str(source.id), "--show-sensors"]
    )

    check_command_ran_without_error(result)
    assert f"No sensors hold data recorded by data source {source.id}" in result.output


def test_list_source_sensors_requires_a_single_source(app, db):
    """Looking up sensors scans the timed_belief table, so it is not allowed for a full listing."""
    from flexmeasures.cli.data_show import list_data_sources

    runner = app.test_cli_runner()
    result = runner.invoke(list_data_sources, ["--show-sensors"])

    assert result.exit_code != 0
    assert "--show-sensors requires --id" in result.output


def test_list_sources_with_deleted_user_and_account(app, db):
    """The user and account columns have no DB-level FK, so a source can outlive what they point to."""
    from flexmeasures.cli.data_show import list_data_sources
    from flexmeasures.data.models.data_sources import DataSource

    orphaned_source = DataSource(name="Orphan", type="demo script")
    orphaned_source.user_id = 999999
    orphaned_source.account_id = 999999
    db.session.add(orphaned_source)
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(list_data_sources, ["--id", str(orphaned_source.id)])

    check_command_ran_without_error(result)
    assert "Orphan" in result.output
    assert "999999" in result.output


def test_show_asset(app, setup_generic_assets):
    from flexmeasures.cli.data_show import show_generic_asset

    runner = app.test_cli_runner()
    result = runner.invoke(
        show_generic_asset,
        ["--id", setup_generic_assets["test_wind_turbine"].id],
    )

    assert "Asset Test wind turbine" in result.output
    assert "No sensors in asset" in result.output
    assert result.exit_code == 1  # command raises a click.Abort Exception


def test_show_asset_with_standardized_sensors_to_show(app, db, setup_generic_assets):
    from flexmeasures.cli.data_show import show_generic_asset

    asset = setup_generic_assets["test_wind_turbine"]
    original_sensors_to_show = asset.sensors_to_show
    asset.sensors_to_show = [{"title": "Power", "plots": [{"sensors": [432, 433]}]}]
    db.session.commit()
    try:
        runner = app.test_cli_runner()
        result = runner.invoke(show_generic_asset, ["--id", asset.id])

        assert "Power: [432, 433]" in result.output
        assert "KeyError" not in result.output
        assert result.exit_code == 1  # command raises a click.Abort Exception
    finally:
        # restore for other tests in this module
        db.session.rollback()
        asset.sensors_to_show = original_sensors_to_show
        db.session.commit()


def test_format_sensors_to_show_supports_asset_plots():
    from flexmeasures.cli.data_show import _format_sensors_to_show

    formatted_sensors_to_show = _format_sensors_to_show(
        [
            {
                "title": "Storage",
                "plots": [
                    {"asset": 12, "flex-model": "soc-min"},
                    {"asset": 13, "flex-context": "consumption-price"},
                    {"unexpected": "plot"},
                ],
            }
        ]
    )

    assert "Storage: asset=12 (flex-model=soc-min)" in formatted_sensors_to_show
    assert "asset=13 (flex-context=consumption-price)" in formatted_sensors_to_show
    assert "{'unexpected': 'plot'}" in formatted_sensors_to_show


def test_show_forecasters(app, db):
    from flexmeasures.cli.data_show import list_forecasters

    runner = app.test_cli_runner()
    result = runner.invoke(list_forecasters)

    # todo: the Custom LGBM model itself should be mentioned, though
    assert "TrainPredictPipeline" in result.output
    check_command_ran_without_error(result)


def test_show_reporters(app, db):
    from flexmeasures.cli.data_show import list_reporters

    runner = app.test_cli_runner()
    result = runner.invoke(list_reporters)

    assert "ProfitOrLossReporter" in result.output
    assert "PandasReporter" in result.output
    check_command_ran_without_error(result)


def test_show_schedulers(app, db):
    from flexmeasures.cli.data_show import list_schedulers

    runner = app.test_cli_runner()
    result = runner.invoke(list_schedulers)

    assert "StorageScheduler" in result.output
    assert "ProcessScheduler" in result.output
    check_command_ran_without_error(result)


def test_plot_beliefs(app, db, setup_beliefs):
    from flexmeasures.cli.data_show import plot_beliefs

    sensor = get_test_sensor(db)

    runner = app.test_cli_runner()
    result = runner.invoke(
        plot_beliefs,
        [
            "--sensor",
            sensor.id,
            "--start",
            "2021-03-28T16:00+01",
            "--duration",
            "PT1H",
        ],
    )

    assert "Beliefs for Sensor 'epex_da'" in result.output
    assert "Data spans an hour" in result.output

    check_command_ran_without_error(result)


@pytest.fixture
def amsterdam_sensor(db, setup_markets, setup_sources) -> Sensor:
    """An hourly sensor in Europe/Amsterdam with one belief, for the event starting at 2021-03-28 15:00 UTC.

    Its timezone is neither UTC (the column default, and what a naive export would show) nor any of the export timezones used below.
    """
    sensor = Sensor(
        name="amsterdam_price",
        generic_asset=setup_markets["epex_da"].generic_asset,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
        timezone="Europe/Amsterdam",
    )
    db.session.add(sensor)
    db.session.flush()
    db.session.add(
        TimedBelief(
            sensor=sensor,
            source=setup_sources["ENTSO-E"],
            event_value=42,
            event_start="2021-03-28 16:00+01",
            belief_horizon=timedelta(0),
        )
    )
    db.session.commit()
    return sensor


def show_beliefs(app, sensors, *options):
    """Run `flexmeasures show beliefs` with the given options, for the hour starting at 2021-03-28 15:00 UTC."""
    from flexmeasures.cli.data_show import plot_beliefs

    sensor_options = [
        option for sensor in sensors for option in ("--sensor", str(sensor.id))
    ]
    return app.test_cli_runner().invoke(
        plot_beliefs,
        [
            *sensor_options,
            "--start",
            "2021-03-28T16:00+01",
            "--duration",
            "PT1H",
            *options,
        ],
    )


def export_beliefs(app, tmp_path, sensors, *options):
    """Run `flexmeasures show beliefs --to-file` with the given options, for the same hour.

    Returns the result of the command and the path of the CSV file it was told to write.
    """
    filepath = tmp_path / "beliefs.csv"
    result = show_beliefs(app, sensors, "--to-file", str(filepath), *options)
    return result, filepath


def first_exported_timestamp(filepath) -> str:
    """The event start of the CSV's only data row, as written (the three header lines hold the names, units and index name)."""
    lines = filepath.read_text().splitlines()
    assert len(lines) == 4, lines
    return lines[-1].split(",")[0]


@pytest.mark.parametrize(
    "timezone_options, expected_timestamp",
    [
        # Without the option, the file uses the sensor's timezone (this used to be naive UTC).
        ([], "2021-03-28 17:00:00+02:00"),
        # An explicit timezone is used (this used to be ignored, giving naive UTC, too).
        (["--export-timezone", "Asia/Tokyo"], "2021-03-29 00:00:00+09:00"),
        # The former name of the option keeps working.
        (["--timezone", "Asia/Tokyo"], "2021-03-29 00:00:00+09:00"),
    ],
)
def test_plot_beliefs_exports_in_the_requested_timezone(
    app, db, amsterdam_sensor, tmp_path, timezone_options, expected_timestamp
):
    result, filepath = export_beliefs(
        app, tmp_path, [amsterdam_sensor], *timezone_options
    )

    check_command_ran_without_error(result)
    assert first_exported_timestamp(filepath) == expected_timestamp
    assert "only applies to the file" not in result.output


def test_plot_beliefs_timezone_alias_is_deprecated(app, db, amsterdam_sensor, tmp_path):
    result, _ = export_beliefs(
        app, tmp_path, [amsterdam_sensor], "--timezone", "Asia/Tokyo"
    )
    assert (
        "Option '--timezone' will be replaced by '--export-timezone'." in result.output
    )

    result, _ = export_beliefs(
        app, tmp_path, [amsterdam_sensor], "--export-timezone", "Asia/Tokyo"
    )
    assert "will be replaced by" not in result.output


def test_plot_beliefs_defaults_to_the_timezone_of_the_first_non_empty_sensor(
    app, db, setup_markets, amsterdam_sensor, tmp_path
):
    """The sensor without data in the requested period is dropped, so it does not decide the timezone (UTC)."""
    empty_sensor = setup_markets["epex_da_production"]

    result, filepath = export_beliefs(app, tmp_path, [empty_sensor, amsterdam_sensor])

    check_command_ran_without_error(result)
    assert f"No data found for sensor {empty_sensor.id}" in result.output
    assert first_exported_timestamp(filepath) == "2021-03-28 17:00:00+02:00"


def test_plot_beliefs_rejects_an_unknown_export_timezone(
    app, db, amsterdam_sensor, tmp_path
):
    result, filepath = export_beliefs(
        app, tmp_path, [amsterdam_sensor], "--export-timezone", "Europe/NotAmsterdam"
    )

    assert result.exit_code == 2
    assert (
        "Invalid value for '--export-timezone' / '--timezone': "
        "Timezone 'Europe/NotAmsterdam' does not exist."
    ) in result.output
    assert not filepath.exists()


def test_plot_beliefs_warns_that_the_export_timezone_needs_a_file(
    app, db, amsterdam_sensor
):
    result = show_beliefs(app, [amsterdam_sensor], "--export-timezone", "Asia/Tokyo")

    check_command_ran_without_error(result)
    assert (
        "--export-timezone only applies to the file written with --to-file"
        in result.output
    )


def test_plot_beliefs_plots_without_timezone_warnings(app, db, amsterdam_sensor):
    """uniplot cannot represent timezones, and numpy warns about each timezone-aware timestamp series it is given."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = show_beliefs(app, [amsterdam_sensor])

    check_command_ran_without_error(result)
    assert not [
        warning
        for warning in caught
        if "no explicit representation of timezones" in str(warning.message)
    ]


def test_cli_help(app):
    """Test that showing help does not throw an error."""
    from flexmeasures.cli import data_show

    runner = app.test_cli_runner()
    for cmd in get_click_commands(data_show):
        result = runner.invoke(cmd, ["--help"])
        assert "Usage" in result.output
        check_command_ran_without_error(result)


@pytest.mark.parametrize(
    "_format, combine_legend",
    [("png", True), ("png", False), ("svg", True), ("svg", False)],
)
def test_export_chart(app, db, setup_beliefs, _format, combine_legend):
    from flexmeasures.cli.data_show import chart

    sensor = get_test_sensor(db)
    sensor_id = sensor.id

    runner = app.test_cli_runner()
    # run test in an isolated file system
    with runner.isolated_filesystem():
        result = runner.invoke(
            chart,
            [
                "--sensor",
                sensor_id,
                "--start",
                "2021-03-28T15:00+01",
                "--end",
                "2021-03-29T16:00+01",
                "--filename",
                f"chart-$entity_type-$id.{_format}",
            ]
            + (["--combine-legend"] if combine_legend else []),
        )

        check_command_ran_without_error(result)
        assert os.path.exists(f"chart-sensor-{sensor_id}.{_format}")
        assert (
            os.path.getsize(f"chart-sensor-{sensor_id}.{_format}") > 100
        )  # bytes: non empty file
