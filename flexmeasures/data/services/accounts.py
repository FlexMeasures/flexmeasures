from __future__ import annotations

from flexmeasures.data.models.user import Account, AccountRole
from flexmeasures.data.models.generic_assets import GenericAsset


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
