from sqlalchemy import select, func

from flexmeasures.cli.tests.utils import check_command_ran_without_error, to_flags
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import Account, User
from flexmeasures.data.services.users import find_user_by_email


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
    data_source_ids_and_account_ids = [
        (ds.id, ds.account_id) for ds in data_sources_before
    ]

    # Add creation audit log record
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
    assert user_creation_audit_log.affected_account_id is None

    # Check that data source lineage is preserved: account_id is NOT nullified after account deletion
    for ds_id, original_account_id in data_source_ids_and_account_ids:
        data_source = fresh_db.session.get(DataSource, ds_id)
        assert (
            data_source is not None
        ), f"Data source {ds_id} should still exist after account deletion."
        assert data_source.account_id == original_account_id, (
            f"Data source {ds_id} account_id should be preserved (not nullified) "
            "after account deletion for lineage purposes."
        )
