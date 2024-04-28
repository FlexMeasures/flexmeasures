from __future__ import annotations

from sqlalchemy import select, func

from flexmeasures.data import db
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import Account, AccountRole
from flexmeasures.data.models.generic_assets import GenericAsset


def get_accounts(
    role_name: str | None = None,
) -> list[Account]:
    """Return a list of Account objects.
    The role_name parameter allows to filter by role.
    """
    if role_name is not None:
        role = db.session.execute(
            select(AccountRole).filter_by(name=role_name)
        ).scalar_one_or_none()
        if role:
            accounts = db.session.scalars(
                select(Account).filter(Account.account_roles.contains(role))
            ).all()
        else:
            return []
    else:
        accounts = db.session.scalars(select(Account)).all()

    return accounts


def get_number_of_assets_in_account(account_id: int) -> int:
    """Get the number of assets in an account."""
    number_of_assets_in_account = db.session.scalar(
        select(func.count()).select_from(GenericAsset).filter_by(account_id=account_id)
    )
    return number_of_assets_in_account


def get_account_roles(account_id: int) -> list[AccountRole]:
    account = db.session.get(Account, account_id)
    if account is None:
        return []
    return account.account_roles


def get_audit_log_records(account: Account) -> list[AuditLog]:
    """
    Get history of account actions
    """
    audit_log_records = (
        db.session.query(AuditLog).filter_by(affected_account_id=account.id).all()
    )
    return audit_log_records
