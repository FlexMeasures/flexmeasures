"""CLI errors when an organisation's plan limits are reached."""

import pytest

from flexmeasures.data.models.user import Plan

pytestmark = pytest.mark.usefixtures("run_as_cli")


def _assert_quota_error(result, message):
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit), result.exception
    assert f"Error: {message}" in result.output
    assert "Traceback" not in result.output
    assert "Success!" not in result.output


def test_add_user_reports_quota_error(
    app, fresh_db, setup_accounts_fresh_db, monkeypatch
):
    account = setup_accounts_fresh_db["Prosumer"]
    account.plan = Plan(name="Free", max_users=0)
    fresh_db.session.commit()
    monkeypatch.setattr(
        "flexmeasures.cli.data_add.getpass.getpass", lambda **_: "password"
    )

    result = app.test_cli_runner().invoke(
        args=[
            "add",
            "user",
            "--username",
            "quota-user",
            "--email",
            "quota@example.com",
            "--account",
            str(account.id),
            "--timezone",
            "UTC",
        ]
    )

    _assert_quota_error(result, "This organisation's plan allows at most 0 users.")


def test_add_asset_reports_quota_error(
    app, fresh_db, setup_accounts_fresh_db, setup_generic_asset_types_fresh_db
):
    account = setup_accounts_fresh_db["Prosumer"]
    account.plan = Plan(name="Free", max_assets=0)
    fresh_db.session.commit()
    asset_type = setup_generic_asset_types_fresh_db["battery"]

    result = app.test_cli_runner().invoke(
        args=[
            "add",
            "asset",
            "--name",
            "quota-asset",
            "--account",
            str(account.id),
            "--asset-type",
            str(asset_type.id),
        ]
    )

    _assert_quota_error(result, "This organisation's plan allows at most 0 assets.")


def test_add_client_reports_quota_error(app, fresh_db, setup_accounts_fresh_db):
    account = setup_accounts_fresh_db["Consultancy"]
    fresh_db.session.commit()
    account.plan = Plan(name="Free", max_clients=0)
    fresh_db.session.commit()

    result = app.test_cli_runner().invoke(
        args=[
            "add",
            "account",
            "--name",
            "quota-client",
            "--consultancy",
            str(account.id),
        ]
    )

    _assert_quota_error(
        result, "This organisation's plan allows at most 0 client organisations."
    )


def test_transfer_asset_reports_quota_error(
    app, fresh_db, setup_accounts_fresh_db, setup_generic_assets_fresh_db
):
    account = setup_accounts_fresh_db["Prosumer"]
    fresh_db.session.commit()
    account.plan = Plan(name="Free", max_assets=0)
    fresh_db.session.commit()
    asset = setup_generic_assets_fresh_db["test_wind_turbine"]
    original_owner_id = asset.account_id

    result = app.test_cli_runner().invoke(
        args=[
            "edit",
            "transfer-ownership",
            "--asset",
            str(asset.id),
            "--new-owner",
            str(account.id),
        ]
    )

    _assert_quota_error(result, "This organisation's plan allows at most 0 assets.")
    fresh_db.session.rollback()
    assert asset.account_id == original_owner_id
