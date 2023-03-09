from typing import List, Optional

from flexmeasures.data.models.user import Account, AccountRole


def get_accounts(
    role_name: Optional[str] = None,
) -> List[Account]:
    """Return a list of Account objects.
    The role_name parameter allows to filter by role.
    """
    account_query = Account.query

    if role_name is not None:
        role = AccountRole.query.filter(AccountRole.name == role_name).one_or_none()
        if role:
            account_query = account_query.filter(Account.account_roles.contains(role))

    return account_query.all()
