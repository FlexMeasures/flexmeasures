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
    data_source_ids_and_lineage = [
        (ds.id, ds.user_id, ds.account_id) for ds in data_sources_before
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
