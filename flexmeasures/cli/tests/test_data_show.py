import os
import pytest
from sqlalchemy import select

from flexmeasures.cli.tests.utils import (
    check_command_ran_without_error,
    get_click_commands,
)
from flexmeasures.tests.utils import get_test_sensor


def test_list_accounts(app, fresh_db, setup_accounts_fresh_db):
    from flexmeasures.cli.data_show import list_accounts

    runner = app.test_cli_runner()
    result = runner.invoke(list_accounts)

    assert "All accounts on this" in result.output
    for account in setup_accounts_fresh_db.values():
        assert account.name in result.output
    check_command_ran_without_error(result)


def test_list_plans(app, fresh_db):
    from flexmeasures.cli.data_show import list_plans
    from flexmeasures.data.models.user import Plan, RateLimitKey

    db = fresh_db
    db.session.add(
        Plan(
            name="Pro",
            trigger_rate_limit="60 per 5 minutes",
            rate_limit_key=RateLimitKey.ACCOUNT,
            max_assets=200,
            legacy=True,
        )
    )
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(list_plans)

    check_command_ran_without_error(result)
    assert "All plans on this" in result.output
    for expected in ("Pro", "60 per 5 minutes", "account"):
        assert expected in result.output
    # Quotas are not enforced yet, so we do not list them
    for not_expected in ("Max assets", "200"):
        assert not_expected not in result.output


def test_list_plans_without_any_plan(app, fresh_db):
    from flexmeasures.cli.data_show import list_plans

    runner = app.test_cli_runner()
    result = runner.invoke(list_plans)

    assert result.exit_code != 0
    assert "No plans created yet" in result.output


def test_list_roles(app, fresh_db, setup_roles_users_fresh_db):
    from flexmeasures.cli.data_show import list_roles

    runner = app.test_cli_runner()
    result = runner.invoke(list_roles)

    assert "Account roles" in result.output
    assert "User roles" in result.output
    for role in ("account-admin", "Supplier", "Dummy"):
        assert role in result.output
    check_command_ran_without_error(result)


def test_list_asset_types(app, fresh_db, setup_generic_asset_types_fresh_db):
    from flexmeasures.cli.data_show import list_asset_types

    runner = app.test_cli_runner()
    result = runner.invoke(list_asset_types)

    for asset_type in setup_generic_asset_types_fresh_db.values():
        assert asset_type.name in result.output
    check_command_ran_without_error(result)


def test_list_sources(app, fresh_db, setup_sources_fresh_db):
    from flexmeasures.cli.data_show import list_data_sources

    runner = app.test_cli_runner()
    result = runner.invoke(list_data_sources)

    for source in setup_sources_fresh_db.values():
        assert source.name in result.output
    check_command_ran_without_error(result)


def test_list_sources_shows_account(app, fresh_db, setup_accounts_fresh_db):
    """The account a source belongs to is what tells apart otherwise identical sources."""
    from flexmeasures.cli.data_show import list_data_sources
    from flexmeasures.data.models.data_sources import DataSource

    account = setup_accounts_fresh_db["Prosumer"]
    fresh_db.session.add(
        DataSource(name="Ada", type="demo script", account_id=account.id)
    )
    fresh_db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(list_data_sources)

    check_command_ran_without_error(result)
    assert "Account ID" in result.output
    assert str(account.id) in result.output


def test_list_source_sensors(app, fresh_db, setup_dummy_data):
    """A source which recorded beliefs on two sensors lists both, with their asset."""
    from flexmeasures.cli.data_show import list_data_sources
    from flexmeasures.data.models.data_sources import DataSource

    source = fresh_db.session.execute(
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


def test_list_source_sensors_without_any_data(app, fresh_db, setup_sources_fresh_db):
    """A source which recorded no beliefs at all says so, rather than showing an empty table."""
    from flexmeasures.cli.data_show import list_data_sources

    fresh_db.session.commit()  # get IDs in DB
    source = setup_sources_fresh_db["Seita"]

    runner = app.test_cli_runner()
    result = runner.invoke(
        list_data_sources, ["--id", str(source.id), "--show-sensors"]
    )

    check_command_ran_without_error(result)
    assert f"No sensors hold data recorded by data source {source.id}" in result.output


def test_list_source_sensors_requires_a_single_source(app, fresh_db):
    """Looking up sensors scans the timed_belief table, so it is not allowed for a full listing."""
    from flexmeasures.cli.data_show import list_data_sources

    runner = app.test_cli_runner()
    result = runner.invoke(list_data_sources, ["--show-sensors"])

    assert result.exit_code != 0
    assert "--show-sensors requires --id" in result.output


def test_list_sources_with_deleted_user_and_account(app, fresh_db):
    """The user and account columns have no DB-level FK, so a source can outlive what they point to."""
    from flexmeasures.cli.data_show import list_data_sources
    from flexmeasures.data.models.data_sources import DataSource

    orphaned_source = DataSource(name="Orphan", type="demo script")
    orphaned_source.user_id = 999999
    orphaned_source.account_id = 999999
    fresh_db.session.add(orphaned_source)
    fresh_db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(list_data_sources, ["--id", str(orphaned_source.id)])

    check_command_ran_without_error(result)
    assert "Orphan" in result.output
    assert "999999" in result.output


def test_show_accounts(app, fresh_db, setup_accounts_fresh_db):
    from flexmeasures.cli.data_show import show_account

    fresh_db.session.flush()  # get IDs in DB

    runner = app.test_cli_runner()
    result = runner.invoke(
        show_account, ["--id", setup_accounts_fresh_db["Prosumer"].id]
    )

    assert "Account Test Prosumer Account" in result.output
    assert "No users in account" in result.output
    check_command_ran_without_error(result)


def test_show_asset(app, fresh_db, setup_generic_assets_fresh_db):
    from flexmeasures.cli.data_show import show_generic_asset

    fresh_db.session.flush()  # get IDs in DB

    runner = app.test_cli_runner()
    result = runner.invoke(
        show_generic_asset,
        ["--id", setup_generic_assets_fresh_db["test_wind_turbine"].id],
    )

    assert "Asset Test wind turbine" in result.output
    assert "No sensors in asset" in result.output
    assert result.exit_code == 1  # command raises a click.Abort Exception


def test_show_asset_with_standardized_sensors_to_show(
    app, fresh_db, setup_generic_assets_fresh_db
):
    from flexmeasures.cli.data_show import show_generic_asset

    asset = setup_generic_assets_fresh_db["test_wind_turbine"]
    asset.sensors_to_show = [{"title": "Power", "plots": [{"sensors": [432, 433]}]}]
    fresh_db.session.flush()

    runner = app.test_cli_runner()
    result = runner.invoke(show_generic_asset, ["--id", asset.id])

    assert "Power: [432, 433]" in result.output
    assert "KeyError" not in result.output
    assert result.exit_code == 1  # command raises a click.Abort Exception


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


def test_plot_beliefs(app, fresh_db, setup_beliefs_fresh_db):
    from flexmeasures.cli.data_show import plot_beliefs

    sensor = get_test_sensor(fresh_db)

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
def test_export_chart(app, fresh_db, setup_beliefs_fresh_db, _format, combine_legend):
    from flexmeasures.cli.data_show import chart

    sensor = get_test_sensor(fresh_db)
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
