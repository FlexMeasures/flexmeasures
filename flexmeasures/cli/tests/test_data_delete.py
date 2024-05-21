from sqlalchemy import select, func

from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import Account, User
from flexmeasures.data.services.users import find_user_by_email


def test_delete_account(
    fresh_db, setup_roles_users_fresh_db, setup_assets_fresh_db, app
):
    """Check account is deleted + old audit log entries get affected_account_id set to None."""
    from flexmeasures.cli.data_delete import delete_account

    prosumer: User = find_user_by_email("test_prosumer_user@seita.nl")
    prosumer_account_id = prosumer.account_id

    num_accounts = fresh_db.session.scalar(select(func.count()).select_from(Account))

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
    assert (
        result.exit_code == 0
        and "Account Test Prosumer Account has been deleted" in result.output
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
