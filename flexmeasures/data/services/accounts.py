from __future__ import annotations

from flexmeasures.data.models.user import Account, AccountRole, RolesAccounts
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data import db


def get_accounts(
    role_name: str | None = None,
) -> list[Account]:
    """Return a list of Account objects.
    The role_name parameter allows to filter by role.
    """
    account_query = Account.query

    if role_name is not None:
        role = AccountRole.query.filter(AccountRole.name == role_name).one_or_none()
        if role:
            account_query = account_query.filter(Account.account_roles.contains(role))
        else:
            return []

    return account_query.all()


def get_number_of_assets_in_account(account_id: int) -> int:
    """Get the number of assets in an account."""
    number_of_assets_in_account = GenericAsset.query.filter(
        GenericAsset.account_id == account_id
    ).count()
    return number_of_assets_in_account


def get_account_roles(account_id: int) -> list[AccountRole]:
    account = Account.query.filter_by(id=account_id).one_or_none()
    if account is None:
        return []
    return account.account_roles


def create_account(name: str, roles: list):
    """
    Create an account for a tenant in the FlexMeasures platform.
    """
    messages = []
    account = db.session.query(Account).filter_by(name=name).one_or_none()
    if account is not None:
        raise ValueError(f"Account '{name}' already exists.")
    account = Account(name=name)
    db.session.add(account)
    if roles:
        for role_name in roles:
            role = AccountRole.query.filter_by(name=role_name).one_or_none()
            if role is None:
                messages |= f"Adding account role {role_name} ..."
                role = AccountRole(name=role_name)
                db.session.add(role)
            db.session.flush()
            db.session.add(RolesAccounts(role_id=role.id, account_id=account.id))
    db.session.commit()
    return account, messages
