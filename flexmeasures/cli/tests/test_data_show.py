import pytest

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.cli.tests.utils import get_click_commands


@pytest.mark.skip_github
def test_list_accounts(app, fresh_db, setup_accounts_fresh_db):
    from flexmeasures.cli.data_show import list_accounts

    runner = app.test_cli_runner()
    result = runner.invoke(list_accounts)

    assert "All accounts on this" in result.output
    for account in setup_accounts_fresh_db.values():
        assert account.name in result.output
    assert result.exit_code == 0


@pytest.mark.skip_github
def test_list_roles(app, fresh_db, setup_roles_users_fresh_db):
    from flexmeasures.cli.data_show import list_roles

    runner = app.test_cli_runner()
    result = runner.invoke(list_roles)

    assert "Account roles" in result.output
    assert "User roles" in result.output
    for role in ("account-admin", "Supplier", "Dummy"):
        assert role in result.output
    assert result.exit_code == 0


@pytest.mark.skip_github
def test_list_asset_types(app, fresh_db, setup_generic_asset_types_fresh_db):
    from flexmeasures.cli.data_show import list_asset_types

    runner = app.test_cli_runner()
    result = runner.invoke(list_asset_types)

    for asset_type in setup_generic_asset_types_fresh_db.values():
        assert asset_type.name in result.output
    assert result.exit_code == 0


@pytest.mark.skip_github
def test_list_sources(app, fresh_db, setup_sources_fresh_db):
    from flexmeasures.cli.data_show import list_data_sources

    runner = app.test_cli_runner()
    result = runner.invoke(list_data_sources)

    for source in setup_sources_fresh_db.values():
        assert source.name in result.output
    assert result.exit_code == 0


@pytest.mark.skip_github
def test_show_accounts(app, fresh_db, setup_accounts_fresh_db):
    from flexmeasures.cli.data_show import show_account

    fresh_db.session.flush()  # get IDs in DB

    runner = app.test_cli_runner()
    result = runner.invoke(
        show_account, ["--id", setup_accounts_fresh_db["Prosumer"].id]
    )

    assert "Account Test Prosumer Account" in result.output
    assert "No users in account" in result.output
    assert result.exit_code == 0


@pytest.mark.skip_github
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
    assert result.exit_code == 0


@pytest.mark.skip_github
def test_plot_beliefs(app, fresh_db, setup_beliefs_fresh_db):
    from flexmeasures.cli.data_show import plot_beliefs

    sensor = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()

    runner = app.test_cli_runner()
    result = runner.invoke(
        plot_beliefs,
        [
            "--sensor-id",
            sensor.id,
            "--start",
            "2021-03-28T16:00+01",
            "--duration",
            "PT1H",
        ],
    )

    assert "Beliefs for Sensor 'epex_da'" in result.output
    assert "Data spans an hour" in result.output

    assert result.exit_code == 0


def test_cli_help(app):
    """Test that showing help does not throw an error."""
    from flexmeasures.cli import data_show

    runner = app.test_cli_runner()
    for cmd in get_click_commands(data_show):
        result = runner.invoke(cmd, ["--help"])
        assert "Usage" in result.output
        assert cmd.__doc__.strip() in result.output
        assert result.exit_code == 0
