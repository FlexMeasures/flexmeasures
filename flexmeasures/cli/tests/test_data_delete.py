import pytest
from sqlalchemy import select, func

from flexmeasures.cli.tests.utils import check_command_ran_without_error, to_flags
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import Account, User
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.utils.secrets_utils import (
    store_account_secret,
    store_asset_secret,
)


def test_delete_account_secret(app, fresh_db, setup_accounts_fresh_db):
    from flexmeasures.cli.data_delete import delete_stored_secret

    app.config["FLEXMEASURES_SECRETS_ENCRYPTION_KEYS"] = {"1": "test-master-key"}
    account = setup_accounts_fresh_db["Prosumer"]
    store_account_secret(account, "platform.access_token", "access-token")
    store_account_secret(account, "platform.refresh_token", "refresh-token")
    fresh_db.session.commit()
    app.config["FLEXMEASURES_SECRETS_ENCRYPTION_KEYS"] = None

    runner = app.test_cli_runner()
    result = runner.invoke(
        delete_stored_secret,
        to_flags(
            {
                "account": account.id,
                "secret": "platform.access_token",
            }
        )
        + ["--force"],
    )

    check_command_ran_without_error(result)
    assert "access-token" not in result.output
    fresh_db.session.refresh(account)
    assert "access_token" not in account.secrets["platform"]
    assert "refresh_token" in account.secrets["platform"]


def test_delete_asset_secret_prunes_empty_parents(
    app, fresh_db, setup_generic_assets_fresh_db
):
    from flexmeasures.cli.data_delete import delete_stored_secret

    app.config["FLEXMEASURES_SECRETS_ENCRYPTION_KEYS"] = {"1": "test-master-key"}
    asset = setup_generic_assets_fresh_db["test_battery"]
    store_asset_secret(asset, "platform.password", "password-value")
    fresh_db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(
        delete_stored_secret,
        to_flags(
            {
                "asset": asset.id,
                "secret": "platform.password",
            }
        )
        + ["--force"],
    )

    check_command_ran_without_error(result)
    assert "password-value" not in result.output
    fresh_db.session.refresh(asset)
    assert asset.secrets == {}


def test_delete_secret_confirmation_mentions_multiple_affected_secrets(
    app, fresh_db, setup_accounts_fresh_db
):
    from flexmeasures.cli.data_delete import delete_stored_secret

    app.config["FLEXMEASURES_SECRETS_ENCRYPTION_KEYS"] = {"1": "test-master-key"}
    account = setup_accounts_fresh_db["Prosumer"]
    store_account_secret(account, "platform.access_token", "access-token")
    store_account_secret(account, "platform.refresh_token", "refresh-token")
    fresh_db.session.commit()
    app.config["FLEXMEASURES_SECRETS_ENCRYPTION_KEYS"] = None

    runner = app.test_cli_runner()
    result = runner.invoke(
        delete_stored_secret,
        [
            "--account",
            str(account.id),
            "--secret",
            "platform",
        ],
        input="n\n",
    )

    assert result.exit_code == 1
    assert "Delete secret 'platform' from account" in result.output
    assert "This affects 2 stored secrets." in result.output
    fresh_db.session.refresh(account)
    assert "platform" in account.secrets


def test_delete_secret_accepts_secret_path_with_dot_in_leaf(
    app, fresh_db, setup_generic_assets_fresh_db
):
    from flexmeasures.cli.data_delete import delete_stored_secret

    app.config["FLEXMEASURES_SECRETS_ENCRYPTION_KEYS"] = {"1": "test-master-key"}
    asset = setup_generic_assets_fresh_db["test_battery"]
    store_asset_secret(asset, ("platform", "token.v2"), "password-value")
    fresh_db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(
        delete_stored_secret,
        [
            "--asset",
            str(asset.id),
            "--secret-path",
            "platform",
            "--secret-path",
            "token.v2",
            "--force",
        ],
    )

    check_command_ran_without_error(result)
    fresh_db.session.refresh(asset)
    assert asset.secrets == {}


def test_delete_secret_rejects_account_and_asset(
    app, fresh_db, setup_accounts_fresh_db, setup_generic_assets_fresh_db
):
    from flexmeasures.cli.data_delete import delete_stored_secret

    fresh_db.session.flush()
    account = setup_accounts_fresh_db["Prosumer"]
    asset = setup_generic_assets_fresh_db["test_battery"]
    runner = app.test_cli_runner()

    with pytest.raises(ValueError, match="Pass exactly one of --account or --asset."):
        runner.invoke(
            delete_stored_secret,
            to_flags(
                {
                    "account": account.id,
                    "asset": asset.id,
                    "secret": "platform.password",
                }
            )
            + ["--force"],
        )


def test_delete_secret_rejects_secret_and_secret_path_together(
    app, fresh_db, setup_accounts_fresh_db
):
    from flexmeasures.cli.data_delete import delete_stored_secret

    account = setup_accounts_fresh_db["Prosumer"]
    runner = app.test_cli_runner()

    with pytest.raises(
        ValueError, match="Pass either --secret or --secret-path, not both."
    ):
        runner.invoke(
            delete_stored_secret,
            [
                "--account",
                str(account.id),
                "--secret",
                "platform.password",
                "--secret-path",
                "platform",
                "--force",
            ],
        )


def test_delete_secret_rejects_more_than_two_secret_path_parts(
    app, fresh_db, setup_accounts_fresh_db
):
    from flexmeasures.cli.data_delete import delete_stored_secret

    account = setup_accounts_fresh_db["Prosumer"]
    runner = app.test_cli_runner()

    with pytest.raises(ValueError, match="Pass --secret-path at most twice."):
        runner.invoke(
            delete_stored_secret,
            [
                "--account",
                str(account.id),
                "--secret-path",
                "platform",
                "--secret-path",
                "nested",
                "--secret-path",
                "token",
                "--force",
            ],
        )


def test_delete_secret_help_includes_examples(app):
    from flexmeasures.cli.data_delete import delete_stored_secret

    result = app.test_cli_runner().invoke(delete_stored_secret, ["--help"])

    check_command_ran_without_error(result)
    assert "Examples:" in result.output
    assert "flexmeasures delete secret --account" in result.output
    assert "--secret-path platform --secret-path token.v2 --force" in result.output


def test_delete_account(
    fresh_db, setup_roles_users_fresh_db, setup_assets_fresh_db, app
):
    """Check account is deleted + old audit log entries get affected_account_id set to None.
    Also check that data source lineage is preserved: account_id is NOT nullified after account deletion.
    """
    from flexmeasures.cli.data_delete import delete_account
    from flexmeasures.data.models.data_sources import DataSource

    prosumer: User = find_user_by_email("test_prosumer_user@seita.nl")
    prosumer_account_id = prosumer.account_id

    num_accounts = fresh_db.session.scalar(select(func.count()).select_from(Account))

    # Find data sources belonging to the account's users (for lineage check after deletion)
    data_sources_before = fresh_db.session.scalars(
        select(DataSource).filter_by(account_id=prosumer_account_id)
    ).all()
    assert (
        len(data_sources_before) > 0
    ), "Data sources linked to the account should exist before deletion."
    data_source_ids_and_lineage = [
        (ds.id, ds.user_id, ds.account_id) for ds in data_sources_before
    ]

    # Add creation audit log record, as that has not automatically been done when setting up test data
    user_creation_audit_log = AuditLog(
        event="User Test Prosumer User created test",
        affected_user_id=prosumer.id,
        affected_account_id=prosumer_account_id,
    )
    fresh_db.session.add(user_creation_audit_log)

    # Delete an account
    cli_input = {
        "id": prosumer_account_id,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(delete_account, to_flags(cli_input), input="y\n")
    check_command_ran_without_error(result)
    assert (
        "Account Test Prosumer Account has been deleted" in result.output
    ), result.exception

    assert (
        fresh_db.session.scalar(select(func.count()).select_from(Account))
        == num_accounts - 1
    )

    user_creation_audit_log = (
        fresh_db.session.query(AuditLog)
        .filter_by(event="User Test Prosumer User created test")
        .one_or_none()
    )
    assert user_creation_audit_log.affected_account_id == prosumer_account_id, (
        "Audit log affected_account_id should be preserved (not nullified) "
        "after account deletion for lineage purposes."
    )
    assert user_creation_audit_log.affected_user_id == prosumer.id, (
        "Audit log affected_user_id should be preserved (not nullified) "
        "after account deletion for lineage purposes."
    )

    # Check that data source lineage is preserved: account_id and user_id are NOT nullified after account deletion
    for ds_id, original_user_id, original_account_id in data_source_ids_and_lineage:
        data_source = fresh_db.session.get(DataSource, ds_id)
        assert (
            data_source is not None
        ), f"Data source {ds_id} should still exist after account deletion."
        assert data_source.account_id == original_account_id, (
            f"Data source {ds_id} account_id should be preserved (not nullified) "
            "after account deletion for lineage purposes."
        )
        if original_user_id is not None:
            assert data_source.user_id == original_user_id, (
                f"Data source {ds_id} user_id should be preserved (not nullified) "
                "after account deletion for lineage purposes."
            )


def test_delete_user(fresh_db, setup_roles_users_fresh_db, setup_assets_fresh_db, app):
    """Check user is deleted + old audit log entries get affected_user_id preserved.
    Also check that data source lineage is preserved: user_id is NOT nullified after user deletion.
    """
    from flexmeasures.cli.data_delete import delete_a_user
    from flexmeasures.data.models.data_sources import DataSource

    prosumer: User = find_user_by_email("test_prosumer_user@seita.nl")
    prosumer_id = prosumer.id
    prosumer_email = prosumer.email
    prosumer_account_id = prosumer.account_id

    num_users = fresh_db.session.scalar(select(func.count()).select_from(User))

    # Find data sources belonging to the user (for lineage check after deletion)
    data_source_before = fresh_db.session.execute(
        select(DataSource).filter_by(user_id=prosumer_id)
    ).scalar_one_or_none()
    if data_source_before is not None:
        data_source_id = data_source_before.id
        data_source_user_id_before = data_source_before.user_id
        data_source_account_id_before = data_source_before.account_id
    else:
        data_source_id = None

    # Add creation audit log record
    user_creation_audit_log = AuditLog(
        event="User Test Prosumer User created test",
        affected_user_id=prosumer_id,
        affected_account_id=prosumer_account_id,
    )
    fresh_db.session.add(user_creation_audit_log)
    fresh_db.session.commit()

    # Delete the user via CLI
    cli_input = {
        "email": prosumer_email,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(delete_a_user, to_flags(cli_input), input="y\n")
    check_command_ran_without_error(result)

    # Check user is deleted
    assert find_user_by_email(prosumer_email) is None
    assert (
        fresh_db.session.scalar(select(func.count()).select_from(User)) == num_users - 1
    )

    # Check that old audit log entries preserve affected_user_id (not set to None)
    user_creation_audit_log_after = (
        fresh_db.session.query(AuditLog)
        .filter_by(event="User Test Prosumer User created test")
        .one_or_none()
    )
    assert user_creation_audit_log_after.affected_user_id == prosumer_id, (
        "Audit log affected_user_id should be preserved (not nullified) "
        "after user deletion for lineage purposes."
    )

    # Check that data source lineage is preserved: user_id is NOT nullified after user deletion
    if data_source_id is not None:
        data_source_after = fresh_db.session.get(DataSource, data_source_id)
        assert (
            data_source_after is not None
        ), f"Data source {data_source_id} should still exist after user deletion."
        assert data_source_after.user_id == data_source_user_id_before, (
            f"Data source {data_source_id} user_id should be preserved (not nullified) "
            "after user deletion for lineage purposes."
        )
        assert data_source_after.account_id == data_source_account_id_before, (
            f"Data source {data_source_id} account_id should be preserved (not nullified) "
            "after user deletion for lineage purposes."
        )
